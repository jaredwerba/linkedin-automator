"""
CSV logger for connection requests and messages sent.
Appends one row per successful action and exposes read-back for the UI.
"""

import csv
import os
from datetime import date, datetime, timedelta
from pathlib import Path

LOG_PATH = Path(os.getenv("LOG_PATH", "connections.csv"))
MSG_LOG_PATH = Path(os.getenv("MSG_LOG_PATH", "messages.csv"))

FIELDS = ["sent_at", "name", "role", "company", "profile_url", "score", "scorer", "note"]
MSG_FIELDS = ["sent_at", "name", "role", "profile_url", "message"]


def _ensure_header():
    """
    Create the CSV with the correct header if it doesn't exist.
    If the file exists but has an old/mismatched header, migrate it in-place:
    re-write all rows under the current FIELDS schema, filling missing columns
    with empty strings and preserving any extra unnamed columns as 'note'.
    """
    if not LOG_PATH.exists() or LOG_PATH.stat().st_size == 0:
        with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
        return

    # Check if the header matches current FIELDS
    with open(LOG_PATH, "r", newline="", encoding="utf-8") as f:
        existing_fields = next(csv.reader(f), [])

    if existing_fields == FIELDS:
        return  # Already up to date

    # Migrate: re-read all rows and rewrite under the new schema
    with open(LOG_PATH, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        old_rows = list(reader)
        old_extra_field = reader.restkey  # key used for unnamed extra columns (None by default)

    migrated = []
    for row in old_rows:
        new_row = {field: row.get(field, "") for field in FIELDS}
        # If old rows had an extra unnamed column (the note landed there), rescue it
        if not new_row["note"] and old_extra_field and row.get(old_extra_field):
            extra = row[old_extra_field]
            new_row["note"] = extra[0] if isinstance(extra, list) else extra
        migrated.append(new_row)

    with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(migrated)


def log_connection(
    name: str,
    role: str,
    company: str,
    profile_url: str,
    score: int,
    ai_scored: bool,
    note: str = "",
):
    """Append one row to the CSV log."""
    _ensure_header()
    row = {
        "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "name": name,
        "role": role,
        "company": company,
        "profile_url": profile_url,
        "score": score,
        "scorer": "AI" if ai_scored else "keywords",
        "note": note,
    }
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writerow(row)


def count_sent_today() -> int:
    """Count CSV rows where sent_at starts with today's date (YYYY-MM-DD)."""
    today = date.today().isoformat()
    if not LOG_PATH.exists():
        return 0
    _ensure_header()
    count = 0
    with open(LOG_PATH, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("sent_at", "").startswith(today):
                count += 1
    return count


def count_sent_this_week() -> int:
    """Count CSV rows sent in the current Mon–Sun calendar week."""
    today = date.today()
    # Monday of the current week
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    # Day after Sunday (exclusive upper bound)
    week_end   = (today - timedelta(days=today.weekday()) + timedelta(days=7)).isoformat()
    if not LOG_PATH.exists():
        return 0
    _ensure_header()
    count = 0
    with open(LOG_PATH, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sent_at = row.get("sent_at", "")[:10]   # "YYYY-MM-DD"
            if week_start <= sent_at < week_end:
                count += 1
    return count


def count_notes_today() -> int:
    """Count CSV rows today that also have a non-empty note (message sent)."""
    today = date.today().isoformat()
    if not LOG_PATH.exists():
        return 0
    _ensure_header()
    count = 0
    with open(LOG_PATH, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("sent_at", "").startswith(today) and row.get("note", "").strip():
                count += 1
    return count


def read_connections() -> list[dict]:
    """Return all logged connections as a list of dicts, newest first."""
    if not LOG_PATH.exists():
        return []
    # Migrate schema if needed before reading
    _ensure_header()
    with open(LOG_PATH, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    # Guarantee every row has all current fields (belt-and-suspenders)
    for row in rows:
        for field in FIELDS:
            if field not in row:
                row[field] = ""
    rows.reverse()
    return rows


# ── Message log (messages.csv) ────────────────────────────────────────────────

def _ensure_msg_header():
    """Create messages.csv with correct header if it doesn't exist."""
    if not MSG_LOG_PATH.exists() or MSG_LOG_PATH.stat().st_size == 0:
        with open(MSG_LOG_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=MSG_FIELDS)
            writer.writeheader()
        return

    with open(MSG_LOG_PATH, "r", newline="", encoding="utf-8") as f:
        existing_fields = next(csv.reader(f), [])

    if existing_fields == MSG_FIELDS:
        return

    # Migrate if schema changed
    with open(MSG_LOG_PATH, "r", newline="", encoding="utf-8") as f:
        old_rows = list(csv.DictReader(f))

    migrated = [{field: row.get(field, "") for field in MSG_FIELDS} for row in old_rows]

    with open(MSG_LOG_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MSG_FIELDS)
        writer.writeheader()
        writer.writerows(migrated)


def log_message(name: str, role: str, profile_url: str, message: str):
    """Append one row to messages.csv."""
    _ensure_msg_header()
    row = {
        "sent_at":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        "name":        name,
        "role":        role,
        "profile_url": profile_url,
        "message":     message,
    }
    with open(MSG_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MSG_FIELDS)
        writer.writerow(row)


def count_messages_today() -> int:
    """Count messages.csv rows where sent_at starts with today's date."""
    today = date.today().isoformat()
    if not MSG_LOG_PATH.exists():
        return 0
    _ensure_msg_header()
    count = 0
    with open(MSG_LOG_PATH, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("sent_at", "").startswith(today):
                count += 1
    return count


def read_messages() -> list[dict]:
    """Return all logged messages as a list of dicts, newest first."""
    if not MSG_LOG_PATH.exists():
        return []
    _ensure_msg_header()
    with open(MSG_LOG_PATH, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    for row in rows:
        for field in MSG_FIELDS:
            if field not in row:
                row[field] = ""
    rows.reverse()
    return rows
