"""
LinkedIn Messaging Automation
Scrapes connections page, clicks Message, types an Ollama-generated
first message directly into the compose box, then clicks Send.
"""

import asyncio
import logging
import os
import traceback
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
from logger import log_message, read_messages
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


# ── Already-messaged guard ────────────────────────────────────────────────────

def _normalize_url(url: str) -> str:
    """Strip query params and trailing slash for reliable comparison."""
    return url.split("?")[0].rstrip("/").lower()


def _load_messaged_urls() -> set[str]:
    """Return a set of normalized profile URLs already in messages.csv."""
    rows = read_messages()
    return {_normalize_url(r.get("profile_url", "")) for r in rows if r.get("profile_url")}


def _load_messaged_names() -> set[str]:
    """Return a set of lowercased names already in messages.csv (fallback when URL is missing)."""
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
        text = text.strip()
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

    # Verify something was typed
    typed = await page.evaluate(f"() => {{ const el = document.querySelector('{compose_sel}'); return el ? el.innerText : ''; }}")
    _fl(f"  Step 5: compose box content after typing: '{typed[:80]}'")
    if not typed.strip():
        _fl("  Step 5: WARNING — compose box appears empty after typing")
        await log("  ⚠ Compose box may be empty — check debug log.")

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
            messaged_urls  = _load_messaged_urls()
            messaged_names = _load_messaged_names()
            _fl(f"Loaded {len(messaged_urls)} messaged URLs, {len(messaged_names)} messaged names")
            await log(f"Already messaged: {len(messaged_urls)} profile(s) in log.")

            filtered = []
            for c in connections:
                url  = _normalize_url(c.get("profileUrl", ""))
                name = c.get("name", "").strip().lower()
                _fl(f"  Check: {c.get('name')} | url={url}")
                if url and url in messaged_urls:
                    _fl(f"    → SKIP (url match)")
                    await log(f"  Skip (already messaged): {c.get('name')}")
                    continue
                if not url and name in messaged_names:
                    _fl(f"    → SKIP (name match)")
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

                success, msg_text = await _send_message_to(page, conn, log)

                if success:
                    total_sent += 1
                    log_message(
                        name=conn["name"],
                        role=conn.get("role", ""),
                        profile_url=conn.get("profileUrl", ""),
                        message=msg_text,
                    )
                    _fl(f"Logged message to CSV for {conn['name']}")
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
