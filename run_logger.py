"""
Run-level log persistence.
Each automation run is stored as one JSON line in runs.jsonl.
Entries accumulate in memory during a run and are flushed on completion.
"""

import json
import os
from datetime import datetime
from pathlib import Path

RUNS_PATH = Path(os.getenv("RUNS_PATH", "runs.jsonl"))

# In-memory buffer: run_id → run dict (mutated live, flushed on finish)
_active_runs: dict[str, dict] = {}


def _detect_level(message: str) -> str:
    """Mirror the level-detection logic from app.js addLog()."""
    lower = message.lower()
    if any(k in lower for k in ("error", "fatal", "captcha")):
        return "error"
    if any(k in lower for k in ("warning", "skipping", "could not", "paused")):
        return "warning"
    if any(k in lower for k in ("✓", "sent", "complete", "done")):
        return "success"
    return "info"


def start_run(companies: list[str]) -> str:
    """Create a new in-memory run record and return its run_id."""
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    _active_runs[run_id] = {
        "run_id": run_id,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "companies": companies,
        "entries": [],
        "total_sent": 0,
        "finished_at": None,
    }
    return run_id


def append_entry(run_id: str, message: str) -> None:
    """Append a log entry to the in-memory run buffer."""
    if run_id not in _active_runs:
        return
    ts = datetime.now().strftime("%H:%M:%S")
    level = _detect_level(message)
    _active_runs[run_id]["entries"].append({
        "ts": ts,
        "message": message,
        "level": level,
    })


def finish_run(run_id: str, total_sent: int) -> None:
    """Finalise the run and flush it to runs.jsonl."""
    if run_id not in _active_runs:
        return
    run = _active_runs[run_id]
    run["total_sent"] = total_sent
    run["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    _flush(run)
    del _active_runs[run_id]


def _flush(run: dict) -> None:
    """Append or update the run record in runs.jsonl."""
    # Read all existing lines
    existing: list[dict] = []
    if RUNS_PATH.exists():
        with open(RUNS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        existing.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    # Replace existing record with same run_id, or append new one
    replaced = False
    for i, rec in enumerate(existing):
        if rec.get("run_id") == run["run_id"]:
            existing[i] = run
            replaced = True
            break
    if not replaced:
        existing.append(run)

    # Rewrite the file
    with open(RUNS_PATH, "w", encoding="utf-8") as f:
        for rec in existing:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_runs() -> list[dict]:
    """Return all completed runs, newest first."""
    if not RUNS_PATH.exists():
        return []
    runs = []
    with open(RUNS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    runs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    runs.sort(key=lambda r: r.get("run_id", ""), reverse=True)
    return runs
