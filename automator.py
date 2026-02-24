import asyncio
import os
import random
from datetime import date
from pathlib import Path
from typing import Callable, Optional
from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeout
from ai import score_title_ai, clear_title_score_cache, generate_connection_note, PROFILE_NAMES
from logger import log_connection, count_sent_today, count_sent_this_week

load_dotenv()

DAILY_CAP  = int(os.getenv("DAILY_CAP",  "30"))
WEEKLY_CAP = int(os.getenv("WEEKLY_CAP", "100"))
DEMO_CAP   = int(os.getenv("DEMO_CAP",   "3"))    # max connections per company per run
TOTAL_HOURS = float(os.getenv("TOTAL_HOURS", "10"))
CHROME_PROFILE_PATH = os.getenv("CHROME_PROFILE_PATH", "").strip()

# Global state — seeded from CSV at import so /status is correct on restart.
_stop_requested  = False
_pause_requested = False
_sent_today      = count_sent_today()
_sent_this_week  = count_sent_this_week()
_session_date    = date.today().isoformat()


def request_stop():
    global _stop_requested
    _stop_requested = True


def request_pause():
    global _pause_requested
    _pause_requested = True


def request_resume():
    global _pause_requested
    _pause_requested = False


def reset_state():
    global _stop_requested, _pause_requested, _sent_today, _sent_this_week, _session_date
    _stop_requested  = False
    _pause_requested = False
    # Always sync from CSV so counts survive server restarts
    _sent_today     = count_sent_today()
    _sent_this_week = count_sent_this_week()
    _session_date   = date.today().isoformat()


def get_sent_today() -> int:
    return _sent_today


def get_sent_this_week() -> int:
    return _sent_this_week


def _detect_chrome_profile() -> str:
    if CHROME_PROFILE_PATH:
        return CHROME_PROFILE_PATH

    import platform
    system = platform.system()

    if system == "Darwin":
        candidates = [
            Path.home() / "Library" / "Application Support" / "Google" / "ChromeLinkedIn",
            Path.home() / "Library" / "Application Support" / "Google" / "Chrome",
        ]
    else:
        candidates = [
            Path.home() / ".config" / "google-chrome-linkedin",
            Path.home() / ".config" / "google-chrome",
        ]

    for path in candidates:
        if path.exists():
            return str(path)

    raise RuntimeError(
        "Could not auto-detect Chrome profile. Set CHROME_PROFILE_PATH in your .env file."
    )


def _detect_chrome_executable() -> str:
    import platform
    system = platform.system()

    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
        ]

    for path in candidates:
        if Path(path).exists():
            return path

    raise RuntimeError("Could not find Chrome executable.")


def _compute_delays(total_requests: int, total_hours: float) -> list[float]:
    total_seconds = total_hours * 3600
    base = total_seconds / max(total_requests, 1)
    delays = [base * random.uniform(0.6, 1.4) for _ in range(total_requests)]
    actual = sum(delays)
    if actual > 0:
        delays = [d * (total_seconds / actual) for d in delays]
    random.shuffle(delays)
    return delays


async def _human_delay(min_ms: int = 800, max_ms: int = 2500, multiplier: float = 1.0):
    base = random.uniform(min_ms / 1000, max_ms / 1000)
    await asyncio.sleep(max(base * multiplier, 0.05))


async def _move_mouse_randomly(page: Page):
    x = random.randint(200, 1100)
    y = random.randint(100, 650)
    await page.mouse.move(x, y, steps=random.randint(5, 15))


async def _check_for_captcha(page: Page) -> bool:
    indicators = [
        "text=Let's do a quick security check",
        "text=Please complete the security check",
        "text=Verify you're a human",
        "text=unusual activity",
        "text=We noticed some unusual activity",
    ]
    for selector in indicators:
        try:
            el = await page.query_selector(selector)
            if el:
                return True
        except Exception:
            pass
    if "checkpoint" in page.url or "challenge" in page.url:
        return True
    return False


async def _find_company_page(page: Page, company_name: str, log: Callable) -> Optional[str]:
    """
    Search LinkedIn for a company and return the URL of the best fuzzy match.
    Uses stable data-view-name attribute instead of randomized CSS classes.
    """
    from fuzzywuzzy import fuzz

    search_url = (
        f"https://www.linkedin.com/search/results/companies/"
        f"?keywords={company_name.replace(' ', '%20')}"
    )
    await log(f"Searching LinkedIn for: {company_name}")
    await page.goto(search_url, wait_until="domcontentloaded")
    await _human_delay(2000, 4000)

    if await _check_for_captcha(page):
        raise RuntimeError("CAPTCHA detected. Please solve it in the browser and restart.")

    # Wait for any company link to appear — use multiple fallback selectors
    try:
        await page.wait_for_selector(
            "[data-view-name='companies-search-result'], "
            ".reusable-search__result-container, "
            "a[href*='/company/']",
            timeout=8000
        )
    except PlaywrightTimeout:
        await log(f"No search results found for '{company_name}'.")
        return None

    # Try to get result cards via stable data attribute first, then fall back
    # to any container that holds company links
    result_cards = await page.query_selector_all("[data-view-name='companies-search-result']")
    if not result_cards:
        result_cards = await page.query_selector_all(".reusable-search__result-container")

    # Fuzzy match company name text — scoped to result cards if found,
    # otherwise fall back to ALL /company/ links on the page (excluding nav)
    best_href = None
    best_score = 0
    best_label = ""

    async def _score_link(link):
        nonlocal best_href, best_score, best_label
        href = await link.get_attribute("href") or ""
        if "/company/" not in href:
            return
        full_text = (await link.inner_text()).strip()
        if not full_text:
            return
        text = full_text.splitlines()[0].strip()
        if not text:
            return
        score = fuzz.token_set_ratio(company_name.lower(), text.lower())
        if score > best_score:
            best_score = score
            best_href = href
            best_label = text

    if result_cards:
        for card in result_cards:
            link = await card.query_selector("a[href*='/company/']")
            if link:
                await _score_link(link)
    else:
        # Last resort: score every /company/ link on the page
        all_links = await page.query_selector_all("a[href*='/company/']")
        for link in all_links:
            await _score_link(link)

    if not best_href or best_score < 40:
        await log(f"Could not fuzzy-match '{company_name}' in results (best score: {best_score}).")
        return None

    if not best_href.startswith("http"):
        best_href = "https://www.linkedin.com" + best_href
    best_href = best_href.split("?")[0].rstrip("/")

    await log(f"Best match: '{best_label}' (score {best_score}) → {best_href}")
    return best_href


async def _go_to_people_tab(page: Page, company_url: str, log: Callable):
    """Navigate directly to the company's People tab."""
    people_url = f"{company_url}/people/"
    await log("Opening People tab...")
    await page.goto(people_url, wait_until="domcontentloaded")
    await _human_delay(2500, 4500)

    if await _check_for_captcha(page):
        raise RuntimeError("CAPTCHA detected on People tab.")

    # Scroll a bit to trigger lazy loading
    await page.mouse.wheel(0, 400)
    await _human_delay(1000, 2000)


async def _scrape_people_cards(page: Page, log: Callable, profile: int = 1) -> list[dict]:
    """
    Scrape profile cards from the company People tab using stable class names
    confirmed from DevTools inspection. Scores by title relevance, best first.
    """
    await log("Reading profiles...")

    # Scroll to trigger lazy loading
    for _ in range(4):
        await page.mouse.wheel(0, 500)
        await _human_delay(600, 1200)

    # Confirmed stable selector from DevTools
    cards = await page.query_selector_all("li.org-people-profile-card__profile-card-spacing")

    if not cards:
        await log("No profile cards found on People tab.")
        return []

    await log(f"Found {len(cards)} profiles — scoring by title relevance...")

    people = []
    for card in cards:
        try:
            # Connect button — aria-label="Invite FirstName LastName to connect"
            # Parse name directly from aria-label for clean, reliable extraction
            connect_btn = await card.query_selector(
                "button[aria-label*='to connect'], "
                "button[aria-label*='Invite'][aria-label*='connect']"
            )
            name = ""
            if connect_btn:
                aria = await connect_btn.get_attribute("aria-label") or ""
                # "Invite John Smith to connect" → "John Smith"
                if aria.lower().startswith("invite ") and " to connect" in aria.lower():
                    name = aria[len("invite "):aria.lower().index(" to connect")].strip()

            # Fallback: profile-info div first line
            if not name:
                info_div = await card.query_selector("div.org-people-profile-card__profile-info")
                if info_div:
                    raw = (await info_div.inner_text()).strip()
                    name = raw.splitlines()[0].strip() if raw else ""

            if not name or name.lower() == "linkedin member":
                continue

            parts = name.split()
            first_name = parts[0] if parts else name

            # Role — second line of profile-info text
            role = ""
            info_div = await card.query_selector("div.org-people-profile-card__profile-info")
            if info_div:
                lines = [l.strip() for l in (await info_div.inner_text()).splitlines() if l.strip()]
                # Skip degree badges ("2nd", "3rd", etc.) and connection labels
                for line in lines[1:]:
                    if not any(x in line.lower() for x in ["degree", "connection", "1st", "2nd", "3rd", "·"]):
                        role = line
                        break
                # If nothing clean found, take second line as-is
                if not role and len(lines) > 1:
                    role = lines[1]

            # Profile URL
            link_el = await card.query_selector("a[href*='/in/']")
            profile_url = ""
            if link_el:
                profile_url = await link_el.get_attribute("href") or ""
                if profile_url and not profile_url.startswith("http"):
                    profile_url = "https://www.linkedin.com" + profile_url

            if not profile_url:
                continue

            # Store aria-label so we re-query button fresh at click time
            # (stored element handles go stale after scrolling/DOM changes)
            connect_aria = await connect_btn.get_attribute("aria-label") if connect_btn else None

            # AI scoring — fast call (num_predict=5), cached per unique title+profile
            ai_score = await score_title_ai(role, profile=profile)
            # Keyword score as fallback if AI returned 0 (unavailable/unparseable)
            kw_score = _score_title(role)
            score = ai_score if ai_score > 0 else kw_score

            people.append({
                "name": name,
                "first_name": first_name,
                "role": role,
                "profile_url": profile_url,
                "score": score,
                "ai_scored": ai_score > 0,
                "connect_aria": connect_aria,
            })
        except Exception:
            continue

    people.sort(key=lambda p: p["score"], reverse=True)

    if people:
        top = people[0]
        scorer = "AI" if top.get("ai_scored") else "keywords"
        await log(f"Top match: {top['name']} — {top['role']} (score: {top['score']}/10 via {scorer})")

    return people


def _score_title(role: str) -> int:
    """Score a job title by relevance as a cloud infrastructure decision maker."""
    if not role:
        return 0

    r = role.lower()
    score = 0

    high = [
        "cto", "chief technology", "vp of engineering", "vp engineering",
        "vp infrastructure", "vp of infrastructure", "vp technology",
        "vp of technology", "head of cloud", "head of engineering",
        "head of infrastructure", "chief architect",
    ]
    for kw in high:
        if kw in r:
            score += 10

    medium = [
        "director of engineering", "director of infrastructure", "director of cloud",
        "director of technology", "director of platform", "engineering manager",
        "cloud architect", "principal engineer", "staff engineer",
    ]
    for kw in medium:
        if kw in r:
            score += 6

    general = [
        "devops", "sre", "site reliability", "platform engineer",
        "infrastructure", "cloud engineer", "devsecops",
        "solutions architect", "technical lead", "engineering",
    ]
    for kw in general:
        if kw in r:
            score += 3

    return score


async def _send_connection(page: Page, prospect: dict, company: str, log: Callable, speed_multiplier: float = 1.0, profile: int = 1) -> bool:
    """
    Send a connection request, with an AI-generated note where possible.
    Strategy 1: click the Connect button on the People tab card.
    Strategy 2: visit the profile page directly.
    Returns True if successful.
    """
    name = prospect.get("name", "Unknown")
    role = prospect.get("role", "")
    connect_aria = prospect.get("connect_aria")
    profile_url = prospect.get("profile_url")

    await log(f"Connecting: {name} ({role})")

    # Remember the People tab URL so we can return after a profile page visit
    people_tab_url = page.url if "/people" in page.url else None

    # ── Strategy 1: click the Connect button on the People tab card ────────────
    # Only attempt if we're still on the People tab — after a Strategy 2 visit
    # the page is a profile page and the aria-label queries can match wrong people.
    if connect_aria and "/people" in page.url:
        try:
            safe_aria = connect_aria.replace("'", "\\'")
            connect_btn = await page.query_selector(f"button[aria-label='{safe_aria}']")

            if not connect_btn:
                # Aria-label may have changed slightly; try partial match
                first_name = name.split()[0] if name else ""
                if first_name:
                    connect_btn = await page.query_selector(
                        f"button[aria-label*='Invite {first_name}'][aria-label*='connect']"
                    )

            if connect_btn:
                # Scroll into view using JS (avoids Playwright stale scroll issues)
                await page.evaluate(
                    "el => el.scrollIntoView({block: 'center', behavior: 'instant'})",
                    connect_btn
                )
                await _human_delay(600, 1000)

                # Verify button is still present and not "Pending" already
                label = (await connect_btn.get_attribute("aria-label") or "").lower()
                text = (await connect_btn.inner_text()).strip().lower()
                if "pending" in label or "pending" in text:
                    await log(f"Already pending for {name} — skipping.")
                    return False, ""

                await connect_btn.click(timeout=5000)
                await _human_delay(1200, 2200)

                # Check if a modal appeared
                modal_detected = False
                for modal_sel in [
                    "div[role='dialog']",
                    "button:has-text('Send without a note')",
                    "button:has-text('Send now')",
                    "button[aria-label*='Send now']",
                    "button:has-text('Send')",
                ]:
                    try:
                        el = await page.query_selector(modal_sel)
                        if el:
                            modal_detected = True
                            break
                    except Exception:
                        pass

                if modal_detected:
                    return await _handle_connect_modal(page, name, role, company, log, speed_multiplier, profile)

                # No modal — check for Pending state (direct send, no note possible)
                try:
                    pending = await page.query_selector(
                        f"button[aria-label*='{name.split()[0]}'][aria-label*='Pending'], "
                        "button:has-text('Pending')"
                    )
                    if pending:
                        await log(f"✓ Sent connection request to {name} ({role}).")
                        return True, ""
                except Exception:
                    pass

                # Try modal one more time with a longer wait
                try:
                    btn = await page.wait_for_selector(
                        "button:has-text('Send without a note'), "
                        "button:has-text('Send now'), "
                        "button:has-text('Send')",
                        timeout=3000
                    )
                    if btn:
                        return await _handle_connect_modal(page, name, role, company, log, speed_multiplier, profile)
                except (PlaywrightTimeout, Exception):
                    pass

                await log(f"Strategy 1 unclear result for {name} — trying profile page.")

        except Exception as e:
            await log(f"Strategy 1 failed for {name}: {e} — trying profile page.")

    # ── Strategy 2: visit the profile page directly ────────────────────────────
    if not profile_url:
        await log(f"Skipping {name} — no profile URL.")
        return False, ""

    await log(f"Opening profile page for {name}...")
    await page.goto(profile_url, wait_until="domcontentloaded")
    await _human_delay(2000, 4000)
    await _move_mouse_randomly(page)

    if await _check_for_captcha(page):
        raise RuntimeError(f"CAPTCHA detected on {name}'s profile.")

    # Small scroll to trigger rendering but stay near the top (header area)
    await page.mouse.wheel(0, random.randint(100, 250))
    await _human_delay(800, 1500)

    # Find the Connect button ONLY in the profile header action area
    # (not in sidebar "People Also Viewed" section)
    connect_btn = await _find_profile_header_connect_btn(page, name)

    if not connect_btn:
        await log(f"No Connect button for {name} — already connected, pending, or not accessible.")
        return False, ""

    try:
        await connect_btn.click(timeout=5000)
    except Exception as e:
        await log(f"Could not click Connect for {name}: {e} — skipping.")
        return False, ""

    await _human_delay(1000, 2000)
    result = await _handle_connect_modal(page, name, role, company, log, speed_multiplier, profile)

    # Navigate back to the People tab so the next prospect's Strategy 1 works
    if people_tab_url and people_tab_url not in page.url:
        try:
            await page.goto(people_tab_url, wait_until="domcontentloaded")
            await _human_delay(1500, 2500)
        except Exception:
            pass  # Non-fatal — next prospect will fall through to Strategy 2

    return result


async def _find_profile_header_connect_btn(page: Page, name: str):
    """
    Return the Connect button for THIS specific person on their profile page.
    Avoids picking up Connect buttons from sidebar 'People Also Viewed'.

    Strategy (most-specific first):
    1. aria-label exact match "Invite <Full Name> to connect" — unique to this person
    2. aria-label partial match with first name — still fairly specific
    3. Scoped within the profile header container (not sidebar/aside)
    4. "More" dropdown in the header
    """
    first_name = name.split()[0] if name else ""
    parts = name.split()
    last_name = parts[-1] if len(parts) > 1 else ""

    # ── Tier 1: Full-name aria-label (most specific, unique to this person) ────
    # LinkedIn aria-label: "Invite Jane Doe to connect"
    if name:
        for aria_selector in [
            f"button[aria-label='Invite {name} to connect']",
            f"button[aria-label*='Invite {name}'][aria-label*='connect']",
        ]:
            try:
                btn = await page.query_selector(aria_selector)
                if btn:
                    # Verify it's not inside an aside/sidebar
                    in_aside = await _is_in_aside(page, btn)
                    if not in_aside:
                        return btn
            except Exception:
                pass

    # ── Tier 2: First + last name partial match ─────────────────────────────────
    if first_name and last_name:
        try:
            btn = await page.query_selector(
                f"button[aria-label*='Invite {first_name}'][aria-label*='{last_name}'][aria-label*='connect']"
            )
            if btn:
                in_aside = await _is_in_aside(page, btn)
                if not in_aside:
                    return btn
        except Exception:
            pass

    # ── Tier 3: Scoped to profile header containers ─────────────────────────────
    header_selectors = [
        ".pv-top-card",
        ".pv-top-card-v2-ctas",
        ".pv-top-card__list-container",
        "[data-view-name='profile-top-card']",
        "main section:first-of-type",
        "section.artdeco-card",
    ]

    for container_sel in header_selectors:
        try:
            container = await page.query_selector(container_sel)
            if not container:
                continue

            for btn_sel in [
                "button[aria-label*='to connect']",
                "button[aria-label*='Invite'][aria-label*='connect']",
                "button:has-text('Connect')",
            ]:
                btn = await container.query_selector(btn_sel)
                if btn:
                    label = (await btn.get_attribute("aria-label") or "").lower()
                    text = (await btn.inner_text()).strip().lower()
                    if "pending" in label or "pending" in text:
                        return None  # Already pending
                    return btn
        except Exception:
            continue

    # ── Tier 4: "More" dropdown in the header ───────────────────────────────────
    for container_sel in header_selectors:
        try:
            container = await page.query_selector(container_sel)
            if not container:
                continue
            more_btn = await container.query_selector(
                "button[aria-label*='More actions'], button:has-text('More')"
            )
            if more_btn:
                await more_btn.click()
                await asyncio.sleep(0.8)
                for btn_sel in [
                    f"button[aria-label*='Invite {first_name}'][aria-label*='connect']",
                    "button[aria-label*='to connect']",
                    "div[role='option']:has-text('Connect')",
                    "li span:has-text('Connect')",
                ]:
                    btn = await page.query_selector(btn_sel)
                    if btn:
                        return btn
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
                break  # Only try More once
        except Exception:
            continue

    return None


async def _is_in_aside(page: Page, element) -> bool:
    """Check if element is inside a sidebar/aside element."""
    try:
        return await page.evaluate(
            """el => {
                let node = el;
                while (node && node !== document.body) {
                    const tag = (node.tagName || '').toLowerCase();
                    if (tag === 'aside') return true;
                    const cls = (typeof node.className === 'string') ? node.className : '';
                    if (cls.includes('aside') || cls.includes('sidebar') ||
                        cls.includes('browsemap') || cls.includes('related-profiles') ||
                        cls.includes('people-also-viewed')) return true;
                    node = node.parentElement;
                }
                return false;
            }""",
            element
        )
    except Exception:
        return False


async def _handle_connect_modal(page: Page, name: str, role: str, company: str, log: Callable, speed_multiplier: float = 1.0, profile: int = 1) -> tuple[bool, str]:
    """
    After clicking Connect, handle the LinkedIn modal. Two variants exist:

    Variant A — "Add a note" modal (profile page):
        [Add a note]  [Send without a note]
        → We click "Add a note", generate + type the note, then click Send.

    Variant B — Direct send modal (People tab card):
        [Send now]
        → No note opportunity; send immediately.

    Falls back gracefully through all known button texts.
    Returns (success: bool, note_sent: str).
    """
    await _human_delay(600, 1000)

    # ── Variant A: check for "Add a note" button ────────────────────────────────
    add_note_btn = None
    for sel in [
        "button:has-text('Add a note')",
        "button[aria-label*='Add a note']",
    ]:
        try:
            btn = await page.query_selector(sel)
            if btn:
                add_note_btn = btn
                break
        except Exception:
            pass

    if add_note_btn:
        # Variant A path — once we enter this branch we NEVER fall through to
        # Variant B. We either succeed or return False so we don't double-send.
        try:
            await add_note_btn.click(timeout=5000)
            await _human_delay(600, 1000)

            # Textarea appears after clicking "Add a note"
            textarea = None
            for sel in [
                "textarea[name='message']",
                "textarea[aria-label*='note']",
                "textarea[aria-label*='message']",
                "div[role='dialog'] textarea",
            ]:
                try:
                    el = await page.wait_for_selector(sel, timeout=4000)
                    if el:
                        textarea = el
                        break
                except (PlaywrightTimeout, Exception):
                    continue

            if not textarea:
                await log(f"Note textarea not found for {name} — skipping.")
                return False, ""

            # Generate note with Ollama
            first_name = name.split()[0] if name else name
            note_text = await generate_connection_note(
                first_name=first_name,
                company=company,
                role=role,
                profile=profile,
            )
            await log(f"Note: \"{note_text}\"")

            # Clear any pre-filled text, then type at human speed
            await textarea.click()
            await page.keyboard.press("Control+a")
            await _human_delay(200, 400)
            typing_delay = max(int(random.randint(30, 80) * speed_multiplier), 5)
            await textarea.type(note_text, delay=typing_delay)
            await _human_delay(600, 1000)

            # Click Send — scoped to the dialog to avoid matching page buttons
            send_sent = False
            for sel in [
                "div[role='dialog'] button:has-text('Send')",
                "div[role='dialog'] button[aria-label*='Send']",
                "button[aria-label='Send invitation']",
            ]:
                try:
                    send_btn = await page.wait_for_selector(sel, timeout=4000)
                    if send_btn:
                        await send_btn.click(timeout=5000)
                        await _human_delay(800, 1500)
                        await log(f"✓ Sent connection request to {name} ({role}) with note.")
                        return True, note_text
                except (PlaywrightTimeout, Exception):
                    continue

            # Send button not found after typing — bail out
            await log(f"Could not find Send button for {name} after typing note — skipping.")
            return False, ""

        except Exception as e:
            await log(f"Note flow failed for {name} ({e}) — skipping.")
            return False, ""

    # ── Variant B: no "Add a note" button — send directly (card modal) ─────────
    # Only reached when LinkedIn skips the note step entirely.
    send_selectors = [
        "div[role='dialog'] button:has-text('Send without a note')",
        "div[role='dialog'] button:has-text('Send now')",
        "div[role='dialog'] button[aria-label*='Send now']",
        "div[role='dialog'] button[aria-label*='Send without']",
        "button[aria-label='Send invitation']",
        "button:has-text('Send without a note')",
        "button:has-text('Send now')",
    ]

    for sel in send_selectors:
        try:
            btn = await page.wait_for_selector(sel, timeout=3000)
            if btn:
                await _human_delay(400, 800)
                await btn.click(timeout=5000)
                await _human_delay(800, 1500)
                await log(f"✓ Sent connection request to {name} ({role}).")
                return True, ""
        except (PlaywrightTimeout, Exception):
            continue

    await log(f"Could not complete modal for {name} — skipping.")
    return False, ""


async def run_automation(company_list: list[str], log: Callable, speed_multiplier: float = 1.0, profile: int = 1):
    """
    Main entry point.
    For each company: find it, open People tab, send up to DEMO_CAP connection
    requests to the most relevant people, then move to the next company.
    Hard ceiling: WEEKLY_CAP per Mon–Sun week.
    speed_multiplier: 1.0 = safe (default), 0.6 = normal, 0.35 = fast, 0.1 = demo
    profile: 1=Cloud Infra General, 2=Cloud Infra OCI Savings, 3=Venture Capital
    """
    global _sent_today, _sent_this_week, _stop_requested

    reset_state()
    clear_title_score_cache()

    # Capture multiplier in a local so all nested helpers see it via closure
    _spd = max(0.05, float(speed_multiplier))

    # Monkey-patch the module-level _human_delay for this run so every helper
    # function automatically uses the current speed without signature changes.
    import automator as _self
    _orig_human_delay = _self._human_delay

    async def _scaled_delay(min_ms: int = 800, max_ms: int = 2500, multiplier: float = 1.0):
        base = random.uniform(min_ms / 1000, max_ms / 1000)
        await asyncio.sleep(max(base * _spd, 0.05))

    _self._human_delay = _scaled_delay

    if _sent_this_week >= WEEKLY_CAP:
        await log(f"Weekly cap of {WEEKLY_CAP} already reached. Try again next week.")
        return
    profile_path = _detect_chrome_profile()
    executable = _detect_chrome_executable()

    await log(f"Chrome profile: {profile_path}")
    profile_name = PROFILE_NAMES.get(profile, f"Profile {profile}")
    await log(f"Profile: {profile_name} | Up to {DEMO_CAP} connections per company | Weekly cap: {WEEKLY_CAP}")

    total_sent = 0

    async with async_playwright() as pw:
        context: BrowserContext = await pw.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            executable_path=executable,
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1280, "height": 800},
        )

        page = context.pages[0] if context.pages else await context.new_page()

        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        try:
            # Warm up on feed
            await log("Loading LinkedIn feed...")
            await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            await _human_delay(2000, 4000)
            await _move_mouse_randomly(page)
            await page.mouse.wheel(0, random.randint(200, 500))
            await _human_delay(1000, 2000)

            if await _check_for_captcha(page):
                raise RuntimeError("CAPTCHA on LinkedIn feed — please solve it and restart.")

            for company in company_list:
                if _stop_requested:
                    break
                if _sent_this_week >= WEEKLY_CAP:
                    await log(f"Weekly cap of {WEEKLY_CAP} reached. Stopping.")
                    break
                await log(f"━━ Company: {company} ━━")

                company_url = await _find_company_page(page, company, log)
                if not company_url:
                    await log(f"Skipping {company} — not found.")
                    continue

                if _stop_requested:
                    break

                await _go_to_people_tab(page, company_url, log)

                if _stop_requested:
                    break

                people = await _scrape_people_cards(page, log, profile=profile)
                if not people:
                    await log(f"No connectable profiles found at {company} — moving on.")
                    continue

                company_sent = 0

                for prospect in people:
                    if _stop_requested:
                        break
                    if company_sent >= DEMO_CAP:
                        await log(f"Reached {DEMO_CAP} connections for {company} — moving to next company.")
                        break
                    if _sent_this_week >= WEEKLY_CAP:
                        await log(f"Weekly cap of {WEEKLY_CAP} reached. Stopping.")
                        break
                    # Handle pause
                    while _pause_requested and not _stop_requested:
                        await log("Paused — waiting to resume...")
                        await asyncio.sleep(5)

                    if _stop_requested:
                        break

                    success, note_sent = await _send_connection(page, prospect, company, log, _spd, profile=profile)

                    if success:
                        company_sent  += 1
                        total_sent    += 1
                        _sent_today   += 1
                        _sent_this_week += 1
                        log_connection(
                            name=prospect.get("name", ""),
                            role=prospect.get("role", ""),
                            company=company,
                            profile_url=prospect.get("profile_url", ""),
                            score=prospect.get("score", 0),
                            ai_scored=prospect.get("ai_scored", False),
                            note=note_sent,
                        )

                        # Short human-like delay between requests
                        if company_sent < DEMO_CAP and not _stop_requested:
                            delay = random.uniform(8, 15) * _spd
                            await log(f"Waiting {delay:.1f}s before next request ({_sent_today} today · {_sent_this_week}/{WEEKLY_CAP} this week)...")
                            await asyncio.sleep(max(delay, 0.5))

                await log(f"Sent {company_sent} connection(s) at {company}.")

            await log(
                f"━━ Done. Sent {total_sent} connection request(s) this run. "
                f"Today: {_sent_today} · This week: {_sent_this_week}/{WEEKLY_CAP}. ━━"
            )

        except RuntimeError as e:
            await log(f"ERROR: {e}")
            raise
        except Exception as e:
            await log(f"Unexpected error: {e}")
            raise
        finally:
            await context.close()
            _self._human_delay = _orig_human_delay
