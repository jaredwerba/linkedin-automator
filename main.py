import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

import automator
import creep
import messenger
from ai import test_ai_connection
from logger import (
    read_connections, count_notes_today, count_sent_this_week,
    read_messages, count_messages_today,
    read_followups, count_followups_pending, count_followups_today,
    weekly_connections_by_day, weekly_messages_by_day, weekly_followups_by_day,
    quarterly_connections_sent, quarterly_messages_sent, quarterly_followups_sent,
    quarterly_connections_accepted, set_accepted_count,
    ACCEPTED_BASELINE, ACCEPTED_BASELINE_DATE,
)
from run_logger import start_run, append_entry, finish_run, read_runs

load_dotenv()

# Track active automation tasks
_automation_task: Optional[asyncio.Task] = None
_msg_task: Optional[asyncio.Task] = None
_followup_task: Optional[asyncio.Task] = None
_creep_task: Optional[asyncio.Task] = None
_active_websocket: Optional[WebSocket] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    if _automation_task and not _automation_task.done():
        _automation_task.cancel()
    if _msg_task and not _msg_task.done():
        _msg_task.cancel()
    if _followup_task and not _followup_task.done():
        _followup_task.cancel()
    if _creep_task and not _creep_task.done():
        _creep_task.cancel()


app = FastAPI(title="LinkedIn Automator", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Models ────────────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    companies: list[str]


class StatusResponse(BaseModel):
    running: bool
    sent_today: int
    daily_cap: int
    sent_this_week: int
    weekly_cap: int
    notes_today: int
    paused: bool


class MsgStatusResponse(BaseModel):
    running: bool
    messages_today: int
    paused: bool


class FollowupStatusResponse(BaseModel):
    running: bool
    pending_count: int
    followed_up_today: int
    paused: bool


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=FileResponse)
async def index():
    return FileResponse("static/index.html")


@app.get("/status", response_model=StatusResponse)
async def get_status():
    return StatusResponse(
        running=_automation_task is not None and not _automation_task.done(),
        sent_today=automator.get_sent_today(),
        daily_cap=int(os.getenv("DAILY_CAP", "30")),
        sent_this_week=automator.get_sent_this_week(),
        weekly_cap=int(os.getenv("WEEKLY_CAP", "100")),
        notes_today=count_notes_today(),
        paused=automator._pause_requested,
    )


@app.get("/msg-status", response_model=MsgStatusResponse)
async def get_msg_status():
    return MsgStatusResponse(
        running=_msg_task is not None and not _msg_task.done(),
        messages_today=count_messages_today(),
        paused=messenger._msg_pause_requested,
    )


@app.get("/followup-status", response_model=FollowupStatusResponse)
async def get_followup_status():
    return FollowupStatusResponse(
        running=_followup_task is not None and not _followup_task.done(),
        pending_count=count_followups_pending(),
        followed_up_today=count_followups_today(),
        paused=messenger._followup_pause_requested,
    )


@app.get("/followups")
async def get_followups():
    rows = read_followups()
    return {"rows": rows, "total": len(rows)}


@app.get("/analytics")
async def get_analytics():
    q_conn   = quarterly_connections_sent()
    q_msg    = quarterly_messages_sent()
    q_fu     = quarterly_followups_sent()
    q_accept = quarterly_connections_accepted()
    conv_pct = round(q_msg / q_conn * 100, 1) if q_conn > 0 else 0.0
    return {
        "weekly": {
            "connections": weekly_connections_by_day(),
            "messages":    weekly_messages_by_day(),
            "followups":   weekly_followups_by_day(),
        },
        "quarterly": {
            "connections_sent":     q_conn,
            "messages_sent":        q_msg,
            "followups_sent":       q_fu,
            "connections_accepted": q_accept,
            "conversion_pct":       conv_pct,
        },
    }


@app.post("/pause")
async def pause():
    automator.request_pause()
    return {"ok": True, "message": "Paused"}


@app.post("/resume")
async def resume():
    automator.request_resume()
    return {"ok": True, "message": "Resumed"}


@app.post("/stop")
async def stop():
    global _automation_task
    automator.request_stop()
    if _automation_task and not _automation_task.done():
        _automation_task.cancel()
    return {"ok": True, "message": "Stop requested"}


@app.get("/test-ai")
async def test_ai():
    result = await test_ai_connection()
    return result


@app.get("/results")
async def get_results():
    rows = read_connections()
    return {"rows": rows, "total": len(rows)}


@app.get("/messages")
async def get_messages():
    rows = read_messages()
    return {"rows": rows, "total": len(rows)}


@app.get("/runs")
async def get_runs():
    runs = read_runs()
    return {"runs": runs, "total": len(runs)}


# ── Connection automation WebSocket ───────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global _automation_task, _active_websocket
    await websocket.accept()
    _active_websocket = websocket

    run_id: Optional[str] = None

    async def log(message: str):
        try:
            await websocket.send_json({"type": "log", "message": message})
        except Exception:
            pass
        if run_id:
            append_entry(run_id, message)

    try:
        data = await websocket.receive_text()
        payload = json.loads(data)

        if payload.get("action") != "run":
            await websocket.send_json({"type": "error", "message": "Expected action: run"})
            return

        companies_raw = payload.get("companies", "")
        speed_multiplier = float(payload.get("speed_multiplier", 1.0))
        speed_multiplier = max(0.05, min(speed_multiplier, 2.0))

        if isinstance(companies_raw, list):
            company_list = [c.strip() for c in companies_raw if c.strip()]
        else:
            company_list = [
                c.strip()
                for c in companies_raw.replace(",", "\n").splitlines()
                if c.strip()
            ]

        if not company_list:
            await websocket.send_json({"type": "error", "message": "Please enter at least one company."})
            return

        run_id = start_run(company_list)

        await websocket.send_json({"type": "started"})
        await log(f"Starting automation for {len(company_list)} company/companies.")
        await log(f"{os.getenv('DEMO_CAP', '3')} connections per company")

        async def run_with_ws():
            try:
                await automator.run_automation(
                    company_list=company_list,
                    log=log,
                    speed_multiplier=speed_multiplier,
                )
                finish_run(run_id, automator.get_sent_today())
                await websocket.send_json({"type": "done"})
            except asyncio.CancelledError:
                await log("Automation cancelled.")
                finish_run(run_id, automator.get_sent_today())
                await websocket.send_json({"type": "done"})
            except Exception as e:
                await log(f"Fatal error: {e}")
                finish_run(run_id, automator.get_sent_today())
                await websocket.send_json({"type": "error", "message": str(e)})

        _automation_task = asyncio.create_task(run_with_ws())

        while not _automation_task.done():
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
                cmd = json.loads(msg)
                action = cmd.get("action")
                if action == "pause":
                    automator.request_pause()
                    await log("Paused by user.")
                elif action == "resume":
                    automator.request_resume()
                    await log("Resumed by user.")
                elif action == "stop":
                    automator.request_stop()
                    _automation_task.cancel()
                    await log("Stop requested by user.")
                    break
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                automator.request_stop()
                break

        await _automation_task

    except WebSocketDisconnect:
        automator.request_stop()
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        _active_websocket = None


# ── Messaging WebSocket ────────────────────────────────────────────────────────

@app.websocket("/ws/msg")
async def msg_websocket_endpoint(websocket: WebSocket):
    global _msg_task
    await websocket.accept()

    async def log(message: str):
        try:
            await websocket.send_json({"type": "log", "message": message})
        except Exception:
            pass

    try:
        data = await websocket.receive_text()
        payload = json.loads(data)

        if payload.get("action") != "msg_run":
            await websocket.send_json({"type": "error", "message": "Expected action: msg_run"})
            return

        msg_cap         = max(1, min(10, int(payload.get("msg_cap", 5))))
        scan_limit      = max(msg_cap, int(payload.get("scan_limit", 20)))
        speed_multiplier = float(payload.get("speed_multiplier", 1.0))
        speed_multiplier = max(0.05, min(speed_multiplier, 2.0))

        await websocket.send_json({"type": "started"})
        await log(f"Starting messaging run — cap: {msg_cap} | scan: {scan_limit}")

        async def run_msg():
            try:
                await messenger.run_messaging(
                    msg_cap=msg_cap,
                    scan_limit=scan_limit,
                    log=log,
                    speed_multiplier=speed_multiplier,
                )
                await websocket.send_json({"type": "done"})
            except asyncio.CancelledError:
                await log("Messaging cancelled.")
                await websocket.send_json({"type": "done"})
            except Exception as e:
                await log(f"Fatal error: {e}")
                await websocket.send_json({"type": "error", "message": str(e)})

        _msg_task = asyncio.create_task(run_msg())

        while not _msg_task.done():
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
                cmd = json.loads(msg)
                action = cmd.get("action")
                if action == "pause":
                    messenger.request_msg_pause()
                    await log("Paused by user.")
                elif action == "resume":
                    messenger.request_msg_resume()
                    await log("Resumed by user.")
                elif action == "stop":
                    messenger.request_msg_stop()
                    _msg_task.cancel()
                    await log("Stop requested by user.")
                    break
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                messenger.request_msg_stop()
                break

        await _msg_task

    except WebSocketDisconnect:
        messenger.request_msg_stop()
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


# ── Follow-up WebSocket ────────────────────────────────────────────────────────

@app.websocket("/ws/followup")
async def followup_websocket_endpoint(websocket: WebSocket):
    global _followup_task
    await websocket.accept()

    async def log(message: str):
        try:
            await websocket.send_json({"type": "log", "message": message})
        except Exception:
            pass

    try:
        data = await websocket.receive_text()
        payload = json.loads(data)

        if payload.get("action") != "followup_run":
            await websocket.send_json({"type": "error", "message": "Expected action: followup_run"})
            return

        followup_cap     = max(1, min(10, int(payload.get("followup_cap", 5))))
        wait_days        = max(0, min(30, int(payload.get("wait_days", 3))))  # 0 = no wait
        speed_multiplier = float(payload.get("speed_multiplier", 1.0))
        speed_multiplier = max(0.05, min(speed_multiplier, 2.0))

        await websocket.send_json({"type": "started"})
        await log(f"Starting follow-up run — cap: {followup_cap} | wait: {wait_days}d")

        async def run_fu():
            try:
                await messenger.run_followups(
                    followup_cap=followup_cap,
                    wait_days=wait_days,
                    log=log,
                    speed_multiplier=speed_multiplier,
                )
                await websocket.send_json({"type": "done"})
            except asyncio.CancelledError:
                await log("Follow-up run cancelled.")
                await websocket.send_json({"type": "done"})
            except Exception as e:
                await log(f"Fatal error: {e}")
                await websocket.send_json({"type": "error", "message": str(e)})

        _followup_task = asyncio.create_task(run_fu())

        while not _followup_task.done():
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
                cmd = json.loads(msg)
                action = cmd.get("action")
                if action == "pause":
                    messenger.request_followup_pause()
                    await log("Paused by user.")
                elif action == "resume":
                    messenger.request_followup_resume()
                    await log("Resumed by user.")
                elif action == "stop":
                    messenger.request_followup_stop()
                    _followup_task.cancel()
                    await log("Stop requested by user.")
                    break
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                messenger.request_followup_stop()
                break

        await _followup_task

    except WebSocketDisconnect:
        messenger.request_followup_stop()
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


# ── Creep Mode ────────────────────────────────────────────────────────────────

@app.get("/creep-log")
async def get_creep_log():
    """Return all creep log entries, newest first."""
    return {"rows": creep.read_creep_log()}


@app.websocket("/ws/creep")
async def creep_websocket_endpoint(websocket: WebSocket):
    global _creep_task
    await websocket.accept()

    async def log(message: str):
        try:
            await websocket.send_json({"type": "log", "message": message})
        except Exception:
            pass

    try:
        data = await websocket.receive_text()
        payload = json.loads(data)

        if payload.get("action") != "creep_run":
            await websocket.send_json({"type": "error", "message": "Expected action: creep_run"})
            return

        profile_cap      = max(1, min(20, int(payload.get("profile_cap", 5))))
        speed_multiplier = float(payload.get("speed_multiplier", 1.0))
        speed_multiplier = max(0.05, min(speed_multiplier, 2.0))

        await websocket.send_json({"type": "started"})
        await log(f"Starting Creep Mode — cap: {profile_cap} profile(s)")

        async def run_creep():
            try:
                await creep.run_creep_mode(
                    profile_cap=profile_cap,
                    log=log,
                    speed_multiplier=speed_multiplier,
                )
                await websocket.send_json({"type": "done"})
            except asyncio.CancelledError:
                await log("Creep Mode cancelled.")
                await websocket.send_json({"type": "done"})
            except Exception as e:
                await log(f"Fatal error: {e}")
                await websocket.send_json({"type": "error", "message": str(e)})

        _creep_task = asyncio.create_task(run_creep())

        while not _creep_task.done():
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
                cmd = json.loads(msg)
                action = cmd.get("action")
                if action == "creep_pause":
                    creep.request_creep_pause()
                    await log("Paused by user.")
                elif action == "creep_resume":
                    creep.request_creep_resume()
                    await log("Resumed by user.")
                elif action == "creep_stop":
                    creep.request_creep_stop()
                    _creep_task.cancel()
                    await log("Stop requested by user.")
                    break
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                creep.request_creep_stop()
                break

        await _creep_task

    except WebSocketDisconnect:
        creep.request_creep_stop()
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


# ── Accepted-connections refresh ───────────────────────────────────────────────

@app.get("/targets")
async def get_targets():
    """Return company names from targets.csv as a list."""
    path = Path("targets.csv")
    if not path.exists():
        return {"companies": []}
    companies = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {"companies": companies}


@app.get("/accepted-count")
async def get_accepted_count():
    """Lightweight endpoint — returns persisted accepted count without launching a browser."""
    return {"accepted": quarterly_connections_accepted()}


@app.get("/obsidian-status")
async def get_obsidian_status():
    """Returns whether the Obsidian Local REST API plugin is reachable."""
    try:
        import obsidian_logger as obs
        enabled = obs.is_enabled()
        return {
            "connected": enabled,
            "configured": obs._ENABLED,
            "base_url": obs.OBSIDIAN_BASE_URL,
            "vault_path": obs.OBSIDIAN_VAULT_PATH,
        }
    except ImportError:
        return {"connected": False, "configured": False}


@app.websocket("/ws/refresh-accepted")
async def refresh_accepted_ws(websocket: WebSocket):
    """
    Opens a Playwright session, navigates to the LinkedIn connections page,
    counts connections since ACCEPTED_BASELINE_DATE, adds ACCEPTED_BASELINE,
    persists the result, and streams progress back to the client.
    """
    from playwright.async_api import async_playwright, BrowserContext
    from automator import _detect_chrome_profile, _detect_chrome_executable

    await websocket.accept()

    async def send(msg: str):
        try:
            await websocket.send_json({"type": "log", "message": msg})
        except Exception:
            pass

    try:
        await send("🔍 Launching browser...")
        profile_path = _detect_chrome_profile()
        executable   = _detect_chrome_executable()

        async with async_playwright() as pw:
            context: BrowserContext = await pw.chromium.launch_persistent_context(
                user_data_dir=profile_path,
                executable_path=executable,
                headless=False,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
                viewport={"width": 1280, "height": 800},
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            )

            await send("🌐 Navigating to connections page...")
            await page.goto(
                "https://www.linkedin.com/mynetwork/invite-connect/connections/",
                wait_until="domcontentloaded",
            )
            await asyncio.sleep(3)

            # Scroll to load more cards
            await send("📜 Loading connection cards...")
            for _ in range(6):
                await page.evaluate("window.scrollBy(0, 800)")
                await asyncio.sleep(0.8)
            await asyncio.sleep(1.5)

            # Count cards with a connected date on or after ACCEPTED_BASELINE_DATE
            new_count: int = await page.evaluate(
                """
                (cutoff) => {
                    const cutoffDate = new Date(cutoff);
                    // LinkedIn connection cards
                    const cards = Array.from(document.querySelectorAll(
                        'li.mn-connection-card, [data-view-name="connection-card"]'
                    ));
                    let count = 0;
                    for (const card of cards) {
                        // Look for "Connected on ..." text anywhere in the card
                        const text = card.innerText || card.textContent || '';
                        const match = text.match(/Connected on (.+)/i);
                        if (!match) continue;
                        const dateStr = match[1].trim().replace(/\\.$/, '');
                        const d = new Date(dateStr);
                        if (!isNaN(d.getTime()) && d >= cutoffDate) count++;
                    }
                    return count;
                }
                """,
                ACCEPTED_BASELINE_DATE,
            )

            total = ACCEPTED_BASELINE + new_count
            set_accepted_count(total)

            await send(f"✅ Found {new_count} new connection(s) since {ACCEPTED_BASELINE_DATE}. Total accepted: {total}")
            await context.close()

        await websocket.send_json({"type": "done", "accepted": total})

    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
