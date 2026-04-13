import asyncio
import os
import random
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Callable, Optional
from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeout
from ai import score_title_ai, clear_title_score_cache, generate_connection_note, PROFILE_NAMES
from logger import log_connection, count_sent_today, count_sent_this_week

load_dotenv()

DAILY_CAP   = int(os.getenv("DAILY_CAP",   "30"))
WEEKLY_CAP  = int(os.getenv("WEEKLY_CAP",  "100"))
RUN_CAP     = int(os.getenv("RUN_CAP",     "30"))   # max connections per single run
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


async def _connect_from_search_results(
    page: Page, title_query: str, log: Callable,
    speed_multiplier: float = 1.0, profile: int = 1, run_cap: int = 30
) -> int:
    """
    Navigate to LinkedIn people search, then send connection requests directly
    from the search result cards.

    LinkedIn now uses hashed CSS classes and the Connect element is an <a> tag
    (not a <button>) with aria-label="Invite {Name} to connect".  We use that
    as the sole reliable anchor, then walk up the DOM to extract card data.

    Returns total connections sent this run.
    """
    global _sent_today, _sent_this_week

    search_url = (
        "https://www.linkedin.com/search/results/people/"
        f"?keywords={urllib.parse.quote(title_query)}"
        "&origin=SWITCH_SEARCH_VERTICAL"
    )

    await log(f"Navigating to search: {title_query}")
    await page.goto(search_url, wait_until="domcontentloaded")
    await _human_delay(2500, 4500)

    if await _check_for_captcha(page):
        raise RuntimeError("CAPTCHA detected. Please solve it and restart.")

    # Wait for Connect links to render (they load after the profile cards)
    try:
        await page.wait_for_selector("a[aria-label*='to connect']", timeout=15000)
    except PlaywrightTimeout:
        await log(f"No connectable profiles found for '{title_query}'.")
        return 0

    # Extra settle time — LinkedIn renders connect links progressively
    await _human_delay(1500, 2500)

    total_sent = 0
    processed: set[str] = set()  # aria-labels we've already attempted
    scroll_attempts = 0
    max_scrolls = 20

    while total_sent < run_cap and scroll_attempts < max_scrolls:
        if _stop_requested:
            break
        if _sent_today >= DAILY_CAP or _sent_this_week >= WEEKLY_CAP:
            break

        # Use JS to extract card data for every visible Connect link at once.
        # This is fast, avoids stale handles, and works with hashed classes.
        cards_data = await page.evaluate("""
            () => {
                const results = [];
                const connectLinks = document.querySelectorAll('a[aria-label*="to connect"]');
                for (const link of connectLinks) {
                    const aria = link.getAttribute('aria-label') || '';
                    // Walk up to find the nearest ancestor that contains a /in/ profile link
                    let card = link.parentElement;
                    for (let i = 0; i < 20 && card; i++, card = card.parentElement) {
                        const profileLink = card.querySelector('a[href*="/in/"]');
                        if (profileLink && profileLink !== link) {
                            // Grab all <p> texts for role / company / location
                            const pTexts = Array.from(card.querySelectorAll('p'))
                                .map(p => p.textContent.trim())
                                .filter(t => t.length > 0);
                            results.push({
                                ariaLabel: aria,
                                name: profileLink.textContent.trim(),
                                profileUrl: profileLink.href.split('?')[0].replace(/\\/$/, ''),
                                pTexts: pTexts,
                            });
                            break;
                        }
                    }
                }
                return results;
            }
        """)

        found_new = False
        new_cards = [c for c in cards_data if c.get("ariaLabel") not in processed]
        if new_cards:
            await log(f"Found {len(new_cards)} connectable profile(s) on page.")

        for card in cards_data:
            if _stop_requested or total_sent >= run_cap:
                break
            if _sent_today >= DAILY_CAP or _sent_this_week >= WEEKLY_CAP:
                break

            aria_label = card.get("ariaLabel", "")
            if aria_label in processed:
                continue
            processed.add(aria_label)
            found_new = True

            name = card.get("name", "").strip()
            profile_url = card.get("profileUrl", "")
            if not name or not profile_url or name.lower() == "linkedin member":
                continue

            # Parse role and company from <p> texts.
            # Typical order: [name + degree, role, location, ...]
            p_texts = card.get("pTexts", [])
            # Filter out the name line and degree badges
            info_lines = [
                t for t in p_texts
                if t != name
                and not t.startswith("About:")
                and "is a mutual" not in t
                and "· " not in t[:5]  # "• 2nd" etc.
            ]
            role = info_lines[0] if len(info_lines) > 0 else ""
            company = info_lines[1] if len(info_lines) > 1 else ""

            first_name = name.split()[0] if name else name

            # Score
            ai_score = await score_title_ai(role, profile=profile)
            kw_score = _score_title(role)
            score = ai_score if ai_score > 0 else kw_score
            ai_scored = ai_score > 0
            scorer_label = "AI" if ai_scored else "kw"

            # Pause check
            while _pause_requested and not _stop_requested:
                await log("Paused — waiting to resume...")
                await asyncio.sleep(5)
            if _stop_requested:
                break

            await log(f"Connecting: {name} ({role}) [{score}/10 {scorer_label}]")

            # Find the connect <a> element by its unique aria-label and click
            safe_aria = aria_label.replace("'", "\\'").replace('"', '\\"')
            connect_el = await page.query_selector(f'a[aria-label="{safe_aria}"]')
            if not connect_el:
                await log(f"Connect link not found for {name} — skipping.")
                continue

            await page.evaluate(
                "el => el.scrollIntoView({block: 'center', behavior: 'smooth'})", connect_el
            )
            await _human_delay(500, 900)

            # Re-query after scroll in case of stale handle
            connect_el = await page.query_selector(f'a[aria-label="{safe_aria}"]')
            if not connect_el:
                await log(f"Connect link gone for {name} after scroll — skipping.")
                continue

            await connect_el.click(timeout=5000)
            await _human_delay(1000, 2000)

            success, note_sent = await _handle_connect_modal(
                page, name, role, company, log, speed_multiplier, profile
            )

            if success:
                total_sent      += 1
                _sent_today     += 1
                _sent_this_week += 1
                log_connection(
                    name=name,
                    role=role,
                    company=company,
                    profile_url=profile_url,
                    score=score,
                    ai_scored=ai_scored,
                    note=note_sent,
                )
                if total_sent < run_cap and not _stop_requested:
                    delay = random.uniform(8, 15) * speed_multiplier
                    await log(
                        f"Waiting {delay:.1f}s... "
                        f"({total_sent}/{run_cap} this run · "
                        f"{_sent_today}/{DAILY_CAP} today)"
                    )
                    await asyncio.sleep(max(delay, 0.5))

        if _stop_requested or total_sent >= run_cap:
            break
        if _sent_today >= DAILY_CAP or _sent_this_week >= WEEKLY_CAP:
            break

        if not found_new:
            # Try Next page button before giving up
            next_btn = await page.query_selector(
                "button[aria-label='Next'], a[aria-label='Next']"
            )
            if next_btn:
                await next_btn.click()
                await _human_delay(2000, 3500)
                scroll_attempts = 0
                continue
            break

        await page.mouse.wheel(0, 2000)
        await _human_delay(1500, 2500)
        scroll_attempts += 1

    return total_sent


def _score_title(role: str) -> int:
    """Seniority-based keyword fallback scorer used when AI scoring is unavailable."""
    if not role:
        return 3  # unknown but has the searched title — give moderate score
    r = role.lower()

    if any(kw in r for kw in ["ceo", "cto", "coo", "cfo", "cpo", "chief ", "president", "founder", "owner"]):
        return 10
    if any(kw in r for kw in ["vp ", " vp", "vice president", "svp", "evp"]):
        return 9
    if any(kw in r for kw in ["director", "head of", "managing director"]):
        return 8
    if any(kw in r for kw in ["manager", "principal", "partner", "lead "]):
        return 6
    if any(kw in r for kw in ["senior ", "sr.", "staff "]):
        return 4
    if any(kw in r for kw in ["associate", "analyst", "specialist", "coordinator", "consultant"]):
        return 3
    if any(kw in r for kw in ["assistant", "junior", "jr.", "entry", "intern", "student"]):
        return 1
    return 3


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
    # Only attempt if we're on a *company* People tab (not search results).
    # Search results use virtual DOM — buttons scroll out of the DOM after loading
    # many profiles, so Strategy 2 (profile page visit) is more reliable there.
    on_company_people_tab = "/people" in page.url and "/search/" not in page.url
    if connect_aria and on_company_people_tab:
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


async def run_automation(title_query: str, log: Callable, speed_multiplier: float = 1.0, profile: int = 1):
    """
    Main entry point.
    Searches LinkedIn people by job title keyword, then sends connection requests
    to the highest-scoring profiles up to the daily/weekly caps.
    speed_multiplier: 1.0 = safe (default), 0.6 = normal, 0.35 = fast, 0.1 = demo
    profile: 1=General Outreach, 2=Senior Focus, 3=Decision Makers
    """
    global _sent_today, _sent_this_week, _stop_requested

    reset_state()
    clear_title_score_cache()

    _spd = max(0.05, float(speed_multiplier))

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
    remaining_today = max(0, DAILY_CAP - _sent_today)
    await log(f"Profile: {profile_name} | Run cap: {RUN_CAP} | Daily remaining: {remaining_today} | Weekly cap: {WEEKLY_CAP}")

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

            if _stop_requested:
                return

            total_sent = await _connect_from_search_results(
                page, title_query, log,
                speed_multiplier=_spd, profile=profile, run_cap=RUN_CAP
            )

            await log(
                f"━━ Done. Sent {total_sent} connection request(s) this run. "
                f"Today: {_sent_today}/{DAILY_CAP} · This week: {_sent_this_week}/{WEEKLY_CAP}. ━━"
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
