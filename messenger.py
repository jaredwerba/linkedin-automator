"""
LinkedIn Messaging Automation
Scrapes connections page, clicks Message, types an Ollama-generated
first message directly into the compose box, then clicks Send.
"""

import asyncio
import logging
import os
import traceback
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeout

from automator import (
    _detect_chrome_profile,
    _detect_chrome_executable,
    _check_for_captcha,
)
from logger import (
    log_message, read_messages,
    seed_followups_from_messages, read_followups, upsert_followup,
    count_followups_pending,
)
import re as _re
from ai import _generate_ollama, _generate_gemini, AI_PROVIDER

load_dotenv()

# ── File logger setup ─────────────────────────────────────────────────────────
_LOG_FILE = Path("messenger_debug.log")

def _setup_file_logger() -> logging.Logger:
    logger = logging.getLogger("messenger")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        fh = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(fh)
    return logger

_flog = _setup_file_logger()


def _fl(msg: str):
    """Write a line to the debug log file."""
    _flog.debug(msg)


# ── Global state ──────────────────────────────────────────────────────────────
_msg_stop_requested  = False
_msg_pause_requested = False


def request_msg_stop():
    global _msg_stop_requested
    _msg_stop_requested = True


def request_msg_pause():
    global _msg_pause_requested
    _msg_pause_requested = True


def request_msg_resume():
    global _msg_pause_requested
    _msg_pause_requested = False


def reset_msg_state():
    global _msg_stop_requested, _msg_pause_requested
    _msg_stop_requested  = False
    _msg_pause_requested = False


# ── Follow-up global state ────────────────────────────────────────────────────
_followup_stop_requested  = False
_followup_pause_requested = False


def request_followup_stop():
    global _followup_stop_requested
    _followup_stop_requested = True


def request_followup_pause():
    global _followup_pause_requested
    _followup_pause_requested = True


def request_followup_resume():
    global _followup_pause_requested
    _followup_pause_requested = False


def reset_followup_state():
    global _followup_stop_requested, _followup_pause_requested
    _followup_stop_requested  = False
    _followup_pause_requested = False


# ── Already-messaged guard ────────────────────────────────────────────────────

def _normalize_url(url: str) -> str:
    """Strip query params and trailing slash for reliable comparison."""
    return url.split("?")[0].rstrip("/").lower()


def _profile_slug(url: str) -> str:
    """
    Extract the /in/username slug — the canonical LinkedIn identity token.
    Used as a format-agnostic fallback when full URL comparison might fail
    due to protocol/subdomain/trailing-slash differences across scraping runs.
    Returns "" if no /in/ path is found.
    """
    m = _re.search(r'/in/([^/?#]+)', _normalize_url(url))
    return m.group(1).lower() if m else ""


def _load_messaged_urls() -> set[str]:
    """Return normalized profile URLs already in messages.csv."""
    rows = read_messages()
    return {_normalize_url(r.get("profile_url", "")) for r in rows if r.get("profile_url")}


def _load_followup_urls() -> set[str]:
    """
    Return normalized profile URLs from followups.csv (any status).
    Anyone in followups.csv has received a first message by definition —
    this is the belt-and-suspenders guard against duplicate first messages
    when messages.csv and followups.csv diverge.
    """
    rows = read_followups()
    return {_normalize_url(r.get("profile_url", "")) for r in rows if r.get("profile_url")}


def _load_messaged_names() -> set[str]:
    """Return lowercased names already in messages.csv (last-resort fallback when URL is missing)."""
    rows = read_messages()
    return {r.get("name", "").strip().lower() for r in rows if r.get("name")}


# ── AI message generation ─────────────────────────────────────────────────────

async def _generate_message(name: str, role: str, log: Callable) -> str:
    """Ask Ollama to write a short, warm first message to a new connection."""
    first = name.split()[0]
    prompt = (
        f"Write a short, friendly LinkedIn first message to {first}, "
        f"who just connected with me. Their role is: {role or 'unknown'}.\n"
        f"Rules:\n"
        f"- 2-3 sentences max\n"
        f"- Warm and genuine, not salesy\n"
        f"- Reference their role if known\n"
        f"- Do NOT mention jobs, recruiting, or opportunities\n"
        f"- Start with 'Hi {first}'\n"
        f"- Return ONLY the message text, nothing else"
    )
    try:
        if AI_PROVIDER == "gemini":
            text = await _generate_gemini(prompt, max_tokens=120, temperature=0.8)
        else:
            text = await _generate_ollama(prompt, max_tokens=120, temperature=0.8)
        text = text.strip().strip('"').strip("'").strip()
        await log(f"  AI wrote: \"{text[:100]}{'...' if len(text) > 100 else ''}\"")
        _fl(f"  AI full message: {text}")
        return text
    except Exception as e:
        _fl(f"  AI error: {e}\n{traceback.format_exc()}")
        await log(f"  AI error: {e} — using fallback message")
        return f"Hi {first}, great to connect! Looking forward to staying in touch."


# ── Scrape connection cards ───────────────────────────────────────────────────

async def _scrape_cards(page: Page, scan_limit: int, log: Callable) -> list[dict]:
    """
    Use JavaScript to extract card data directly from the DOM.
    The message button wrapper [data-view-name="message-button"] is confirmed present.
    """
    # Scroll to load more cards
    for _ in range(3):
        await page.mouse.wheel(0, 800)
        await asyncio.sleep(0.8)

    cards_data = await page.evaluate(f"""
        () => {{
            const wrappers = Array.from(document.querySelectorAll('[data-view-name="message-button"]'));
            const results = [];
            const seenHrefs = new Set();

            for (const wrapper of wrappers.slice(0, {scan_limit})) {{
                try {{
                    const msgLink = wrapper.querySelector('a[aria-label="Message"]') || wrapper.querySelector('a');
                    const msgHref = msgLink ? (msgLink.getAttribute("href") || "") : "";
                    if (!msgHref || seenHrefs.has(msgHref)) continue;
                    seenHrefs.add(msgHref);

                    // Walk up until we find an ancestor with a /in/ link
                    let card = wrapper;
                    for (let i = 0; i < 3; i++) {{
                        if (card.parentElement) card = card.parentElement;
                        if (card.querySelector('a[href*="/in/"]')) break;
                    }}

                    let name = "";
                    let profileUrl = "";
                    const inLinks = card.querySelectorAll('a[href*="/in/"]');
                    for (const a of inLinks) {{
                        const txt = a.innerText.trim();
                        if (txt && txt.length < 60 && !txt.includes("\\n")) {{
                            name = txt;
                            const href = a.getAttribute("href") || "";
                            profileUrl = href.startsWith("http")
                                ? href.split("?")[0]
                                : "https://www.linkedin.com" + href.split("?")[0];
                            break;
                        }}
                    }}

                    let role = "";
                    const paras = card.querySelectorAll("p");
                    for (const p of paras) {{
                        const txt = p.innerText.trim();
                        if (txt && txt !== name && !txt.toLowerCase().startsWith("connected on")) {{
                            role = txt;
                            break;
                        }}
                    }}

                    if (name && msgHref) {{
                        results.push({{ name, role, profileUrl, msgHref }});
                    }}
                }} catch(e) {{}}
            }}
            return results;
        }}
    """)

    _fl(f"Scrape result ({len(cards_data)} cards):")
    for c in cards_data:
        _fl(f"  name={c.get('name')} | profileUrl={c.get('profileUrl')} | msgHref={c.get('msgHref','')[:60]}")

    await log(f"Scraped {len(cards_data)} cards with name + message link.")
    return cards_data


# ── Send one message ──────────────────────────────────────────────────────────

async def _send_message_to(page: Page, conn: dict, log: Callable) -> tuple[bool, str]:
    name     = conn["name"]
    role     = conn.get("role", "")
    msg_href = conn["msgHref"]

    _fl(f"--- Messaging {name} ---")
    _fl(f"  role: {role}")
    _fl(f"  msgHref: {msg_href}")
    _fl(f"  current page url: {page.url}")

    await log(f"── {name} ({role or 'no role'})")

    # ── 1. Navigate directly to the compose URL ───────────────────────────────
    # More reliable than clicking the button: avoids overlay state issues when
    # multiple messages are sent in one run.
    full_url = msg_href if msg_href.startswith("http") else "https://www.linkedin.com" + msg_href
    if "interop=msgOverlay" not in full_url:
        full_url += ("&" if "?" in full_url else "?") + "interop=msgOverlay"

    _fl(f"  Step 1: navigating to {full_url}")
    await log("  Opening compose window...")
    await page.goto(full_url, wait_until="domcontentloaded")
    await asyncio.sleep(2.5)

    if await _check_for_captcha(page):
        _fl("  Step 1: CAPTCHA detected")
        await log("  ✗ CAPTCHA — skipping.")
        return False, ""

    # ── 2. Wait for the visible compose text box ──────────────────────────────
    _fl("  Step 2: waiting for visible compose box")
    compose_box = None
    compose_sel = None
    for sel in [
        ".msg-form__contenteditable",
        "div[role='textbox']",
        "div[contenteditable='true']",
    ]:
        try:
            el = await page.wait_for_selector(sel, state="visible", timeout=8000)
            if el:
                compose_box = el
                compose_sel = sel
                _fl(f"  Step 2: found via {sel}")
                await log(f"  Compose box ready.")
                break
        except PlaywrightTimeout:
            _fl(f"  Step 2: timeout on {sel}")
            continue

    if not compose_box:
        _fl("  Step 2: FAILED — compose box never became visible")
        html = await page.evaluate("() => document.body.innerHTML.slice(0, 2000)")
        _fl(f"  Page HTML snippet:\n{html}")
        await log("  ✗ Compose box not found — skipping.")
        return False, ""

    # ── 3. Dismiss the LinkedIn Premium AI prompt if present ──────────────────
    _fl("  Step 3: checking for AI prompt dismiss button")
    await asyncio.sleep(0.5)
    for dismiss_sel in [
        "button[aria-label='Dismiss']",
        "button[aria-label='Close']",
        "button[aria-label*='close' i]",
        "button[aria-label*='dismiss' i]",
    ]:
        try:
            el = await page.query_selector(dismiss_sel)
            if el and await el.is_visible():
                _fl(f"  Step 3: dismissing with {dismiss_sel}")
                await el.click()
                await log("  Dismissed AI prompt.")
                await asyncio.sleep(0.4)
                break
        except Exception as ex:
            _fl(f"  Step 3: dismiss error: {ex}")

    # ── 4. Generate message with Ollama ───────────────────────────────────────
    _fl("  Step 4: generating message with Ollama")
    msg_text = await _generate_message(name, role, log)

    # ── 5. Focus and type into the compose box ────────────────────────────────
    # Re-query fresh after Ollama (handles stale element handles)
    _fl("  Step 5: re-querying compose box before typing")
    compose_box = await page.query_selector(compose_sel)
    if not compose_box:
        # Broader fallback
        for fb in [".msg-form__contenteditable", "div[role='textbox']", "div[contenteditable='true']"]:
            compose_box = await page.query_selector(fb)
            if compose_box:
                _fl(f"  Step 5: fallback selector used: {fb}")
                break

    if not compose_box:
        _fl("  Step 5: FAILED — compose box gone after Ollama")
        await log("  ✗ Compose box gone after AI generation — skipping.")
        return False, ""

    # Use JS to focus the element, then type via keyboard
    _fl("  Step 5: focusing compose box via JS")
    await page.evaluate("el => { el.focus(); el.click(); }", compose_box)
    await asyncio.sleep(0.3)

    _fl(f"  Step 5: typing message ({len(msg_text)} chars)")
    await page.keyboard.type(msg_text, delay=20)
    await asyncio.sleep(0.5)

    # Verify something was typed — if box is empty the DOM has gone stale.
    # Proceeding to click Send with an empty box causes the element-detached
    # crash seen in logs; abort this contact cleanly instead.
    typed = await page.evaluate(f"() => {{ const el = document.querySelector('{compose_sel}'); return el ? el.innerText : ''; }}")
    _fl(f"  Step 5: compose box content after typing: '{typed[:80]}'")
    if not typed.strip():
        _fl("  Step 5: compose box empty after typing — DOM went stale. Aborting this contact.")
        await log("  ✗ Compose box empty after typing — skipping (will retry next run).")
        return False, ""

    # ── 6. 5-second preview countdown ────────────────────────────────────────
    await log("  Sending in 5s — click Stop to cancel...")
    for _ in range(5):
        if _msg_stop_requested:
            await page.keyboard.press("Escape")
            return False, ""
        await asyncio.sleep(1.0)

    if _msg_stop_requested:
        await page.keyboard.press("Escape")
        return False, ""

    # ── 7. Click Send ─────────────────────────────────────────────────────────
    _fl("  Step 7: finding Send button")
    send_btn = None
    for sel in [
        "button.msg-form__send-button",
        "button[aria-label='Send']",
        "button[aria-label*='Send' i]",
        ".msg-overlay-conversation-bubble button[type='submit']",
        "button[type='submit']",
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                send_btn = el
                _fl(f"  Step 7: found Send button via {sel}")
                break
        except Exception as ex:
            _fl(f"  Step 7: error checking {sel}: {ex}")

    if send_btn:
        await send_btn.click()
        _fl("  Step 7: clicked Send button")
    else:
        _fl("  Step 7: Send button not found — trying Ctrl+Enter")
        await log("  Send button not found — trying Ctrl+Enter...")
        await page.keyboard.press("Control+Enter")

    await asyncio.sleep(1.5)
    _fl(f"  Step 7: done — message sent to {name}")
    await log(f"  ✓ Sent to {name}.")
    return True, msg_text


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_messaging(
    msg_cap: int,
    scan_limit: int,
    log: Callable,
    speed_multiplier: float = 1.0,
):
    reset_msg_state()
    msg_cap    = max(1, min(10, msg_cap))
    scan_limit = max(msg_cap, scan_limit)

    _fl(f"\n{'='*60}")
    _fl(f"RUN START  {datetime.now().isoformat()}  cap={msg_cap} scan={scan_limit} speed={speed_multiplier}")
    _fl(f"{'='*60}")

    await log(f"Starting messaging run — cap: {msg_cap} | scan: {scan_limit}")
    await log("Opening Chrome...")

    profile_path = _detect_chrome_profile()
    executable   = _detect_chrome_executable()
    _fl(f"profile_path: {profile_path}")
    _fl(f"executable:   {executable}")

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
            await log("Navigating to connections page...")
            _fl("Navigating to connections page")
            await page.goto(
                "https://www.linkedin.com/mynetwork/invite-connect/connections/",
                wait_until="domcontentloaded",
            )
            await asyncio.sleep(3)

            if await _check_for_captcha(page):
                await log("CAPTCHA detected — please solve it and restart.")
                return

            connections = await _scrape_cards(page, scan_limit, log)
            if not connections:
                await log("No messageable connections found.")
                return

            # ── Filter already-messaged ───────────────────────────────────────
            # Three-layer guard — checked in order:
            #   1. Full normalized URL match against messages.csv
            #   2. /in/slug match — catches URL format variations across runs
            #   3. Full normalized URL match against followups.csv (anyone in
            #      followups.csv received a first message by definition)
            #   4. Name match — last resort when profile URL is missing entirely
            messaged_urls  = _load_messaged_urls()
            followup_urls  = _load_followup_urls()
            all_sent_urls  = messaged_urls | followup_urls
            all_sent_slugs = {_profile_slug(u) for u in all_sent_urls if _profile_slug(u)}
            messaged_names = _load_messaged_names()

            _fl(f"Guard sets — messages.csv: {len(messaged_urls)} | followups.csv: {len(followup_urls)} | slugs: {len(all_sent_slugs)} | names: {len(messaged_names)}")
            await log(f"Already messaged: {len(messaged_urls)} in messages log, {len(followup_urls)} in followup tracker.")

            filtered = []
            for c in connections:
                url  = _normalize_url(c.get("profileUrl", ""))
                slug = _profile_slug(url)
                name = c.get("name", "").strip().lower()
                _fl(f"  Check: {c.get('name')} | url={url} | slug={slug}")

                if url and url in all_sent_urls:
                    _fl(f"    → SKIP (full URL match)")
                    await log(f"  Skip (already messaged): {c.get('name')}")
                    continue
                if slug and slug in all_sent_slugs:
                    _fl(f"    → SKIP (slug match — URL format variation)")
                    await log(f"  Skip (already messaged): {c.get('name')}")
                    continue
                if not url and name in messaged_names:
                    _fl(f"    → SKIP (name match — no URL)")
                    await log(f"  Skip (name match): {c.get('name')}")
                    continue
                _fl(f"    → QUEUE")
                filtered.append(c)

            skipped = len(connections) - len(filtered)
            connections = filtered

            if skipped:
                await log(f"Skipping {skipped} already-messaged connection(s).")
            if not connections:
                await log("All connections already messaged — nothing to do.")
                return

            await log(f"Ready to message {len(connections)} new connection(s). Cap: {msg_cap}")

            total_sent = 0
            for conn in connections:
                if _msg_stop_requested:
                    break
                if total_sent >= msg_cap:
                    await log(f"Cap of {msg_cap} reached.")
                    break

                while _msg_pause_requested and not _msg_stop_requested:
                    await log("Paused...")
                    await asyncio.sleep(5)

                if _msg_stop_requested:
                    break

                # Return to connections page before each message
                if "invite-connect/connections" not in page.url:
                    _fl(f"Returning to connections page (was: {page.url})")
                    await page.goto(
                        "https://www.linkedin.com/mynetwork/invite-connect/connections/",
                        wait_until="domcontentloaded",
                    )
                    await asyncio.sleep(2.5)

                try:
                    success, msg_text = await _send_message_to(page, conn, log)
                except Exception as send_exc:
                    err_str = str(send_exc)
                    _fl(f"Exception sending to {conn['name']}: {err_str[:200]}")
                    # Browser-dead errors: re-raise so the outer handler closes
                    # the context cleanly and the run ends.
                    if any(k in err_str for k in ("Target page", "browser has been closed", "TargetClosed", "context or browser")):
                        await log(f"  ✗ Browser closed unexpectedly — ending run.")
                        raise
                    # Per-contact DOM errors: log, skip, continue to next person.
                    await log(f"  ✗ Send error for {conn['name']} — skipping (will retry next run).")
                    success, msg_text = False, ""

                if success:
                    total_sent += 1
                    sent_url = conn.get("profileUrl", "")
                    log_message(
                        name=conn["name"],
                        role=conn.get("role", ""),
                        profile_url=sent_url,
                        message=msg_text,
                    )
                    # Update in-memory guard sets so a duplicate card in the
                    # same scrape batch can never trigger a second send.
                    norm = _normalize_url(sent_url)
                    slug = _profile_slug(sent_url)
                    all_sent_urls.add(norm)
                    if slug:
                        all_sent_slugs.add(slug)
                    _fl(f"Logged message to CSV for {conn['name']} | added {norm} to in-run guard")
                    if total_sent < msg_cap and not _msg_stop_requested:
                        delay = max(8 * speed_multiplier, 1.0)
                        await log(f"  Waiting {delay:.0f}s before next message...")
                        await asyncio.sleep(delay)

            _fl(f"RUN END — {total_sent} sent")
            await log(f"━━ Done. {total_sent} message(s) sent. ━━")

        except Exception as e:
            _fl(f"EXCEPTION: {e}\n{traceback.format_exc()}")
            await log(f"Error: {e}")
            raise
        finally:
            await context.close()
            _fl("Browser closed.")


# ── Follow-up: profile URN extraction ────────────────────────────────────────

async def _get_profile_urn(page: Page, profile_url: str, log: Callable) -> str:
    """
    Navigate to a LinkedIn profile page and extract the fsd_profile URN ID
    (e.g. 'ACoAADnPWLk...') from embedded page data.

    LinkedIn embeds entity data in <code> tags as JSON blobs that contain
    the fsd_profile ID. This is the same ID used in compose URLs.

    Returns the ID string, or "" on failure.
    """
    _fl(f"  _get_profile_urn: navigating to {profile_url}")
    await page.goto(profile_url, wait_until="domcontentloaded")
    await asyncio.sleep(2.5)

    if await _check_for_captcha(page):
        _fl("  _get_profile_urn: CAPTCHA detected")
        await log("  ✗ CAPTCHA on profile page.")
        return ""

    profile_id = await page.evaluate(r"""
        () => {
            // LinkedIn embeds entity data in <code> tags as JSON
            const codes = Array.from(document.querySelectorAll('code'));
            for (const c of codes) {
                const m = c.textContent.match(/"fsd_profile:([\w-]+)"/);
                if (m) return m[1];
            }
            // Broader fallback: scan full page HTML for URN pattern
            const m2 = document.documentElement.innerHTML.match(/urn:li:fsd_profile:([\w-]+)/);
            if (m2) return m2[1];
            return null;
        }
    """)

    if profile_id:
        _fl(f"  _get_profile_urn: found ID {profile_id[:20]}...")
    else:
        _fl(f"  _get_profile_urn: not found on {profile_url}")

    return profile_id or ""


def _build_compose_url(profile_id: str) -> str:
    """Build a direct LinkedIn compose URL from a fsd_profile ID."""
    encoded = urllib.parse.quote(f"urn:li:fsd_profile:{profile_id}", safe="")
    return (
        f"https://www.linkedin.com/messaging/compose/"
        f"?profileUrn={encoded}&recipient={profile_id}&interop=msgOverlay"
    )


# ── Follow-up: reply detection ────────────────────────────────────────────────

async def _click_message_button_on_profile(page: Page, log: Callable) -> bool:
    """
    Click the Message button on a LinkedIn profile page (it's a <button>, not <a>).
    Waits for the compose overlay to appear.
    Returns True if the compose box became visible, False otherwise.
    """
    _fl("  Clicking Message button on profile page...")

    # Try multiple selectors — LinkedIn uses different markup depending on connection status
    msg_btn = None
    for sel in [
        "button[aria-label^='Message']",            # "Message Tomer" etc.
        "button.message-anywhere-button",
        "button[data-control-name='message']",
        "div.pvs-profile-actions button:has-text('Message')",
        "main button:has-text('Message')",
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                msg_btn = el
                _fl(f"  Found Message button via: {sel}")
                break
        except Exception:
            pass

    # Broader fallback: find any visible button whose text is exactly "Message"
    if not msg_btn:
        try:
            buttons = await page.query_selector_all("button")
            for btn in buttons:
                try:
                    txt = (await btn.inner_text()).strip()
                    vis = await btn.is_visible()
                    if vis and txt == "Message":
                        msg_btn = btn
                        _fl("  Found Message button via text scan")
                        break
                except Exception:
                    pass
        except Exception:
            pass

    if not msg_btn:
        _fl("  Message button not found on profile page")
        await log("  ⚠ Message button not found on profile page.")
        return False

    await msg_btn.click()
    _fl("  Clicked Message button — waiting for compose overlay...")
    await asyncio.sleep(2.0)

    # Wait for the compose box to appear
    for sel in [
        ".msg-form__contenteditable",
        "div[role='textbox']",
        "div[contenteditable='true']",
    ]:
        try:
            el = await page.wait_for_selector(sel, state="visible", timeout=6000)
            if el:
                _fl(f"  Compose overlay appeared (selector: {sel})")
                return True
        except PlaywrightTimeout:
            continue

    _fl("  Compose overlay did not appear after clicking Message button")
    return False


async def _check_replied(page: Page, profile_url: str, log: Callable) -> bool:
    """
    Navigate to the profile page, click Message to open the thread overlay,
    then check if the last message bubble is from them (replied) or us (no reply).

    Returns True if they replied, False otherwise (including on error).
    Page is left on the profile with the compose overlay open if not replied,
    ready for follow-up text to be typed straight in.
    """
    _fl(f"  Reply check: navigating to {profile_url}")
    try:
        await page.goto(profile_url, wait_until="domcontentloaded")
        await asyncio.sleep(2.5)

        if await _check_for_captcha(page):
            _fl("  Reply check: CAPTCHA on profile page")
            await log("  ✗ CAPTCHA on profile — skipping.")
            return False

        # Click the Message button and wait for overlay
        overlay_open = await _click_message_button_on_profile(page, log)
        if not overlay_open:
            return False

        await asyncio.sleep(1.0)

        # Check last message sender in the thread overlay:
        # .msg-s-event-listitem--other = they sent last → replied
        # .msg-s-event-listitem--self  = we sent last   → no reply
        last_sender = await page.evaluate("""
            () => {
                const items = Array.from(document.querySelectorAll(
                    '.msg-s-event-listitem--other, .msg-s-event-listitem--self'
                ));
                if (items.length === 0) return 'unknown';
                const last = items[items.length - 1];
                return last.classList.contains('msg-s-event-listitem--other') ? 'other' : 'self';
            }
        """)

        _fl(f"  Reply check: last_sender={last_sender}")
        return last_sender == "other"

    except Exception as e:
        _fl(f"  Reply check exception: {e}\n{traceback.format_exc()}")
        await log(f"  ⚠ Reply check error: {e} — assuming no reply.")
        return False


# ── Follow-up: message generation ─────────────────────────────────────────────

async def _generate_followup_message(
    name: str, role: str, first_msg: str, log: Callable
) -> str:
    """Ask Ollama to write a gentle single follow-up nudge."""
    first = name.split()[0]
    snippet = first_msg[:120].strip()
    prompt = (
        f"Write a short, gentle follow-up LinkedIn message to {first}, "
        f"a {role or 'professional'}, who hasn't replied yet.\n"
        f"My original message was: \"{snippet}\"\n"
        f"Rules:\n"
        f"- 1-2 sentences max\n"
        f"- Warm, not pushy\n"
        f"- Do NOT mention jobs, recruiting, or opportunities\n"
        f"- Do NOT repeat the original message verbatim\n"
        f"- Start with 'Hi {first}'\n"
        f"- Return ONLY the message text, nothing else"
    )
    try:
        if AI_PROVIDER == "gemini":
            text = await _generate_gemini(prompt, max_tokens=80, temperature=0.7)
        else:
            text = await _generate_ollama(prompt, max_tokens=80, temperature=0.7)
        text = text.strip().strip('"').strip("'").strip()
        await log(f"  AI follow-up: \"{text[:100]}{'...' if len(text) > 100 else ''}\"")
        _fl(f"  AI follow-up full: {text}")
        return text
    except Exception as e:
        _fl(f"  AI follow-up error: {e}")
        await log(f"  AI error: {e} — using fallback")
        return f"Hi {first}, just wanted to check in — hope all is well!"


# ── Follow-up: main entry point ───────────────────────────────────────────────

async def run_followups(
    followup_cap: int,
    wait_days: int,
    log: Callable,
    speed_multiplier: float = 1.0,
):
    """
    1. Seed followups.csv from messages.csv (idempotent).
    2. Find pending connections whose first message is older than wait_days.
    3. For each: check if they replied; if not, send a follow-up.
    """
    reset_followup_state()
    followup_cap = max(1, min(10, followup_cap))
    wait_days    = max(0, min(30, wait_days))  # 0 = no wait (test mode)

    _fl(f"\n{'='*60}")
    _fl(f"FOLLOWUP RUN START  {datetime.now().isoformat()}  cap={followup_cap} wait_days={wait_days} speed={speed_multiplier}")
    _fl(f"{'='*60}")

    await log(f"Starting follow-up run — cap: {followup_cap} | wait: {wait_days} day(s)")

    # ── 1. Seed from messages.csv ──────────────────────────────────────────────
    seeded = seed_followups_from_messages()
    if seeded:
        await log(f"Seeded {seeded} new connection(s) into follow-up tracker.")
        _fl(f"Seeded {seeded} rows from messages.csv into followups.csv")

    # ── 2. Filter candidates ───────────────────────────────────────────────────
    from datetime import timedelta as _timedelta
    cutoff_dt = datetime.now() - _timedelta(days=wait_days)
    cutoff    = cutoff_dt.strftime("%Y-%m-%d %H:%M")

    all_rows  = read_followups()
    candidates = []
    for row in reversed(all_rows):  # chronological
        if row.get("status") != "pending":
            continue
        sent_at = row.get("first_msg_sent_at", "")
        if not sent_at:
            continue
        # Include if first message was sent AT or BEFORE the cutoff time
        # (i.e. old enough to follow up on). When wait_days=0 cutoff=now,
        # so all pending rows qualify.
        if sent_at <= cutoff:
            candidates.append(row)

    await log(f"Found {len(candidates)} pending connection(s) older than {wait_days} day(s).")
    _fl(f"Candidates: {len(candidates)}")

    if not candidates:
        await log("Nothing to follow up on yet — check back later.")
        return

    await log("Opening Chrome...")

    profile_path = _detect_chrome_profile()
    executable   = _detect_chrome_executable()
    _fl(f"profile_path: {profile_path}")
    _fl(f"executable:   {executable}")

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
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )

        try:
            total_sent = 0
            for row in candidates:
                if _followup_stop_requested:
                    break
                if total_sent >= followup_cap:
                    await log(f"Cap of {followup_cap} reached.")
                    break

                while _followup_pause_requested and not _followup_stop_requested:
                    await log("Paused...")
                    await asyncio.sleep(5)

                if _followup_stop_requested:
                    break

                name        = row.get("name", "Unknown")
                role        = row.get("role", "")
                profile_url = row.get("profile_url", "")
                first_msg   = row.get("first_msg_sent_at", "")

                await log(f"── {name} ({role or 'no role'})")
                _fl(f"Processing {name} | url={profile_url}")

                now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

                # ── 3a. Navigate to profile and click Message ──────────────
                # _check_replied goes to the profile, clicks Message, opens
                # the thread overlay, and checks if they replied.
                # If not replied, the compose overlay is already open and ready.
                replied = await _check_replied(page, profile_url, log)

                if replied:
                    await log(f"  ✓ {name} already replied — marking done.")
                    _fl(f"  {name} replied — updating status")
                    upsert_followup(profile_url, replied_at=now_str, status="replied")
                    # Close the overlay and move on
                    await page.keyboard.press("Escape")
                    continue

                # ── 3b. Compose overlay is open — find the compose box ─────
                compose_box = None
                compose_sel = None
                for sel in [
                    ".msg-form__contenteditable",
                    "div[role='textbox']",
                    "div[contenteditable='true']",
                ]:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        compose_box = el
                        compose_sel = sel
                        _fl(f"  Compose box found via {sel}")
                        break

                if not compose_box:
                    await log(f"  ✗ Compose overlay didn't open for {name} — skipping.")
                    _fl(f"  Compose box not found for {name}")
                    continue

                # ── 3c. Dismiss AI prompt if it appeared ───────────────────
                await asyncio.sleep(0.5)
                for dismiss_sel in [
                    "button[aria-label='Dismiss']", "button[aria-label='Close']",
                    "button[aria-label*='close' i]", "button[aria-label*='dismiss' i]",
                ]:
                    try:
                        el = await page.query_selector(dismiss_sel)
                        if el and await el.is_visible():
                            await el.click()
                            await asyncio.sleep(0.4)
                            break
                    except Exception:
                        pass

                # ── 3d. Generate follow-up message ─────────────────────────
                from logger import read_messages as _read_msgs
                orig_msgs = _read_msgs()
                orig_text = ""
                norm_url  = _normalize_url(profile_url)
                for m in orig_msgs:
                    if _normalize_url(m.get("profile_url", "")) == norm_url:
                        orig_text = m.get("message", "")
                        break

                followup_text = await _generate_followup_message(name, role, orig_text, log)

                # ── 3e. Type into the compose box ──────────────────────────
                # Re-query fresh after Ollama call
                compose_box = await page.query_selector(compose_sel)
                if not compose_box:
                    for fb in [".msg-form__contenteditable", "div[role='textbox']", "div[contenteditable='true']"]:
                        compose_box = await page.query_selector(fb)
                        if compose_box:
                            compose_sel = fb
                            break

                if not compose_box:
                    await log(f"  ✗ Compose box gone after AI — skipping {name}.")
                    continue

                await page.evaluate("el => { el.focus(); el.click(); }", compose_box)
                await asyncio.sleep(0.3)
                await page.keyboard.type(followup_text, delay=20)
                await asyncio.sleep(0.5)

                # ── 3f. 5-second preview countdown ────────────────────────
                await log("  Sending in 5s — click Stop to cancel...")
                for _ in range(5):
                    if _followup_stop_requested:
                        await page.keyboard.press("Escape")
                        break
                    await asyncio.sleep(1.0)

                if _followup_stop_requested:
                    await page.keyboard.press("Escape")
                    break

                # ── 3g. Click Send ─────────────────────────────────────────
                send_btn = None
                for sel in [
                    "button.msg-form__send-button",
                    "button[aria-label='Send']",
                    "button[aria-label*='Send' i]",
                    ".msg-overlay-conversation-bubble button[type='submit']",
                    "button[type='submit']",
                ]:
                    try:
                        el = await page.query_selector(sel)
                        if el and await el.is_visible():
                            send_btn = el
                            break
                    except Exception:
                        pass

                if send_btn:
                    await send_btn.click()
                    _fl("  Clicked Send button")
                else:
                    _fl("  Send button not found — using Ctrl+Enter")
                    await page.keyboard.press("Control+Enter")

                await asyncio.sleep(1.5)
                total_sent += 1

                # ── 3h. Log to followups.csv ───────────────────────────────
                upsert_followup(profile_url, follow_up_sent_at=now_str, status="followed_up")
                _fl(f"  Follow-up sent and logged for {name}")
                await log(f"  ✓ Follow-up sent to {name}.")

                if total_sent < followup_cap and not _followup_stop_requested:
                    delay = max(8 * speed_multiplier, 1.0)
                    await log(f"  Waiting {delay:.0f}s before next...")
                    await asyncio.sleep(delay)

            _fl(f"FOLLOWUP RUN END — {total_sent} sent")
            await log(f"━━ Done. {total_sent} follow-up(s) sent. ━━")

        except Exception as e:
            _fl(f"FOLLOWUP EXCEPTION: {e}\n{traceback.format_exc()}")
            await log(f"Error: {e}")
            raise
        finally:
            await context.close()
            _fl("Browser closed.")
