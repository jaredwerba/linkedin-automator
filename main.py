import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

import automator
from ai import test_ai_connection
from logger import read_connections, count_notes_today, count_sent_this_week
from run_logger import start_run, append_entry, finish_run, read_runs

load_dotenv()

# Track active automation task
_automation_task: Optional[asyncio.Task] = None
_active_websocket: Optional[WebSocket] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    if _automation_task and not _automation_task.done():
        _automation_task.cancel()


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


@app.get("/runs")
async def get_runs():
    runs = read_runs()
    return {"runs": runs, "total": len(runs)}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global _automation_task, _active_websocket
    await websocket.accept()
    _active_websocket = websocket

    # Will be set once the run starts
    run_id: Optional[str] = None

    async def log(message: str):
        # Send to live feed
        try:
            await websocket.send_json({"type": "log", "message": message})
        except Exception:
            pass
        # Persist to run history
        if run_id:
            append_entry(run_id, message)

    try:
        data = await websocket.receive_text()
        payload = json.loads(data)

        if payload.get("action") != "run":
            await websocket.send_json({"type": "error", "message": "Expected action: run"})
            return

        companies_raw = payload.get("companies", "")

        # Parse company list (list or newline/comma string)
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

        # Start the run history record
        run_id = start_run(company_list)

        await websocket.send_json({"type": "started"})
        await log(f"Starting automation for {len(company_list)} company/companies.")
        await log(f"Daily cap: {os.getenv('DAILY_CAP', '20')} | {os.getenv('DEMO_CAP', '3')} connections per company")

        async def run_with_ws():
            try:
                await automator.run_automation(
                    company_list=company_list,
                    log=log,
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

        # Keep websocket open to receive pause/stop signals
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
