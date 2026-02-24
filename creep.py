"""
Creep Mode — quietly like recent posts of connections.
Reads connection requests from connections.csv, visits each LinkedIn profile,
finds the most recent post, and likes it. Logs every visit to creep.csv.
"""

import asyncio
import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Awaitable

from playwright.async_api import async_playwright, BrowserContext, TimeoutError as PlaywrightTimeout

from automator import (
    _detect_chrome_profile,
    _detect_chrome_executable,
    _check_for_captcha,
)
from logger import read_connections

try:
    import obsidian_logger as _obs
except ImportError:
    _obs = None

# ── CSV storage ────────────────────────────────────────────────────────────────

CREEP_LOG_PATH = Path(os.getenv("CREEP_LOG_PATH", "creep.csv"))
CREEP_FIELDS = ["creeped_at", "name", "profile_url", "post_liked"]


def _ensure_creep_header():
    """Create creep.csv with correct header if it doesn't exist or is empty."""
    if not CREEP_LOG_PATH.exists() or CREEP_LOG_PATH.stat().st_size == 0:
        with open(CREEP_LOG_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CREEP_FIELDS)
            writer.writeheader()
        return

    with open(CREEP_LOG_PATH, "r", newline="", encoding="utf-8") as f:
        existing_fields = next(csv.reader(f), [])

    if existing_fields != CREEP_FIELDS:
        # Migrate if schema changed
        with open(CREEP_LOG_PATH, "r", newline="", encoding="utf-8") as f:
            old_rows = list(csv.DictReader(f))
        migrated = [{field: row.get(field, "") for field in CREEP_FIELDS} for row in old_rows]
        with open(CREEP_LOG_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CREEP_FIELDS)
            writer.writeheader()
            writer.writerows(migrated)


def append_creep_entry(name: str, profile_url: str, post_liked: bool) -> None:
    """Append one row to creep.csv."""
    _ensure_creep_header()
    row = {
        "creeped_at":  datetime.now().strftime("%Y-%m-%d %H:%M"),
        "name":        name,
        "profile_url": profile_url,
        "post_liked":  "yes" if post_liked else "no",
    }
    with open(CREEP_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CREEP_FIELDS)
        writer.writerow(row)

    if _obs:
        try:
            _obs.on_post_liked(name=name, profile_url=profile_url, liked=post_liked)
        except Exception:
            pass


def read_creep_log() -> list[dict]:
    """Return all creep log rows as a list of dicts, newest first."""
    if not CREEP_LOG_PATH.exists():
        return []
    _ensure_creep_header()
    with open(CREEP_LOG_PATH, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    for row in rows:
        for field in CREEP_FIELDS:
            if field not in row:
                row[field] = ""
    rows.reverse()
    return rows


# ── Control state ──────────────────────────────────────────────────────────────

_creep_stop_requested  = False
_creep_pause_requested = False


def request_creep_stop():
    global _creep_stop_requested
    _creep_stop_requested = True


def request_creep_pause():
    global _creep_pause_requested
    _creep_pause_requested = True


def request_creep_resume():
    global _creep_pause_requested
    _creep_pause_requested = False


def reset_creep_state():
    global _creep_stop_requested, _creep_pause_requested
    _creep_stop_requested  = False
    _creep_pause_requested = False


# ── Human-like delay helpers ───────────────────────────────────────────────────

async def _human_delay(base: float = 2.0, multiplier: float = 1.0):
    """Async sleep with a small random jitter."""
    import random
    t = base * multiplier + random.uniform(0.5, 1.5)
    await asyncio.sleep(t)


# ── Main automation ────────────────────────────────────────────────────────────

async def run_creep_mode(
    profile_cap: int,
    log: Callable[[str], Awaitable[None]],
    speed_multiplier: float = 1.0,
):
    """
    Visit up to `profile_cap` profiles from connections.csv,
    find each person's most recent post, and like it.
    Results are logged to creep.csv.
    """
    reset_creep_state()

    # Load connections (newest first), deduplicate by profile_url
    all_connections = read_connections()
    seen_urls: set[str] = set()
    profiles: list[dict] = []
    for conn in all_connections:
        url = conn.get("profile_url", "").strip()
        if url and url not in seen_urls:
            seen_urls.add(url)
            profiles.append(conn)

    if not profiles:
        await log("No connections found in connections.csv.")
        return

    cap = min(profile_cap, len(profiles))
    await log(f"Creeping {cap} profile(s) from {len(profiles)} connection(s)...")

    profile_path = _detect_chrome_profile()
    executable   = _detect_chrome_executable()

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

        liked_count = 0

        for i, conn in enumerate(profiles[:cap]):
            if _creep_stop_requested:
                await log("Stop requested — ending Creep Mode.")
                break

            # Handle pause
            while _creep_pause_requested:
                await asyncio.sleep(1)
                if _creep_stop_requested:
                    break

            name        = conn.get("name", "Unknown")
            profile_url = conn.get("profile_url", "").strip()

            await log(f"[{i+1}/{cap}] Visiting {name}…")

            try:
                await page.goto(profile_url, wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(1.5)

                # Scroll down progressively to load the activity/posts section
                for scroll_step in [800, 600, 500]:
                    await page.evaluate(f"window.scrollBy(0, {scroll_step})")
                    await asyncio.sleep(1.0)

                # Dump all buttons on page for diagnostics
                btn_info = await page.evaluate("""
                    () => {
                        return Array.from(document.querySelectorAll('button')).map(b => ({
                            label: b.getAttribute('aria-label') || '',
                            pressed: b.getAttribute('aria-pressed') || '',
                            cls: b.className.substring(0, 80),
                            visible: b.offsetParent !== null,
                            text: (b.innerText || '').trim().substring(0, 30),
                        })).filter(b => b.visible);
                    }
                """)
                # Log buttons that look like social action buttons
                social = [b for b in btn_info if any(k in (b['label']+b['cls']+b['text']).lower()
                          for k in ['like','react','comment','repost','send','share'])]
                await log(f"  Visible social buttons ({len(social)}): {[(b['label'] or b['text'] or b['cls'][:40]) for b in social]}")

                # Strategy: find the first Like button by any means
                like_btn = await page.evaluate_handle("""
                    () => {
                        const all = Array.from(document.querySelectorAll('button'));

                        // 1. aria-label contains "like" and not already pressed
                        let btn = all.find(b => {
                            const lbl = (b.getAttribute('aria-label') || '').toLowerCase();
                            return lbl.includes('like') && b.getAttribute('aria-pressed') !== 'true'
                                   && b.offsetParent !== null;
                        });
                        if (btn) return btn;

                        // 2. First button inside a social-actions bar (reaction row at bottom of post)
                        //    LinkedIn profile activity uses li.social-action-button or
                        //    ul.social-details-social-counts ~ ul buttons
                        const actionRows = document.querySelectorAll(
                            'ul.social-details-social-counts, ' +
                            'div.feed-shared-social-action-bar, ' +
                            'div[class*="social-action"], ' +
                            'div[class*="reaction-bar"]'
                        );
                        for (const row of actionRows) {
                            // first button in the row is typically Like
                            const first = row.querySelector('button');
                            if (first && first.offsetParent !== null) return first;
                        }

                        // 3. Any visible button whose SVG contains the thumbs-up path
                        //    (data-test-id or icon class approach)
                        btn = all.find(b => {
                            if (!b.offsetParent) return false;
                            const svg = b.querySelector('svg');
                            if (!svg) return false;
                            const use = svg.querySelector('use');
                            if (use) {
                                const href = use.getAttribute('href') || use.getAttribute('xlink:href') || '';
                                return href.includes('like') || href.includes('thumb');
                            }
                            // check aria on the li parent
                            const li = b.closest('li');
                            if (li) {
                                const liCls = li.className || '';
                                return liCls.includes('like') || liCls.includes('reaction');
                            }
                            return false;
                        });
                        if (btn) return btn;

                        return null;
                    }
                """)

                is_null = await page.evaluate("el => el === null", like_btn)
                if is_null:
                    await log(f"  — No like button found for {name} (profile may have no posts or activity hidden).")
                    append_creep_entry(name, profile_url, False)
                    await _human_delay(2.0, speed_multiplier)
                    await _check_for_captcha(page)
                    continue

                like_el = like_btn.as_element()
                if not like_el:
                    await log(f"  — Could not get element handle for {name}.")
                    append_creep_entry(name, profile_url, False)
                    await _human_delay(2.0, speed_multiplier)
                    await _check_for_captcha(page)
                    continue

                # Scroll into view and click
                await like_el.scroll_into_view_if_needed()
                await asyncio.sleep(0.6)
                await like_el.click()
                await asyncio.sleep(1.2)

                liked_count += 1
                await log(f"  ✓ Liked {name}'s post.")
                append_creep_entry(name, profile_url, True)

            except PlaywrightTimeout:
                await log(f"  ⚠ Timeout visiting {name} — skipping.")
                append_creep_entry(name, profile_url, False)
            except Exception as e:
                await log(f"  ✗ Error on {name}: {e}")
                append_creep_entry(name, profile_url, False)

            await _human_delay(3.0, speed_multiplier)
            await _check_for_captcha(page, log)

        await context.close()

    await log(f"Creep Mode complete — liked {liked_count}/{cap} post(s).")
