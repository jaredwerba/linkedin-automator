"""
CSV logger for connection requests and messages sent.
Appends one row per successful action and exposes read-back for the UI.
"""

import csv
import os
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import obsidian_logger as _obs
except ImportError:
    _obs = None

LOG_PATH = Path(os.getenv("LOG_PATH", "connections.csv"))
MSG_LOG_PATH = Path(os.getenv("MSG_LOG_PATH", "messages.csv"))

# ── Accepted-connections tracking ─────────────────────────────────────────────
ACCEPTED_BASELINE      = 15          # confirmed accepted count before automated tracking
ACCEPTED_BASELINE_DATE = "2026-02-21"  # scrape counts connections on/after this date
_ACCEPTED_COUNT_PATH   = Path("accepted_count.txt")

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

    if _obs:
        try:
            _obs.on_connection_sent(
                name=name, role=role, company=company,
                profile_url=profile_url, score=score,
                scorer="AI" if ai_scored else "keywords", note=note,
            )
        except Exception:
            pass


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

    if _obs:
        try:
            _obs.on_message_sent(
                name=name, role=role,
                profile_url=profile_url, message=message,
            )
        except Exception:
            pass


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


# ── Follow-up log (followups.csv) ─────────────────────────────────────────────

FOLLOWUP_LOG_PATH = Path(os.getenv("FOLLOWUP_LOG_PATH", "followups.csv"))
FOLLOWUP_FIELDS = [
    "profile_url", "name", "role",
    "first_msg_sent_at", "follow_up_sent_at", "replied_at", "status",
]


def _normalize_url_for_log(url: str) -> str:
    return url.split("?")[0].rstrip("/").lower()


def _ensure_followup_header():
    """Create followups.csv with correct header if it doesn't exist."""
    if not FOLLOWUP_LOG_PATH.exists() or FOLLOWUP_LOG_PATH.stat().st_size == 0:
        with open(FOLLOWUP_LOG_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FOLLOWUP_FIELDS)
            writer.writeheader()
        return

    with open(FOLLOWUP_LOG_PATH, "r", newline="", encoding="utf-8") as f:
        existing_fields = next(csv.reader(f), [])

    if existing_fields == FOLLOWUP_FIELDS:
        return

    # Migrate if schema changed
    with open(FOLLOWUP_LOG_PATH, "r", newline="", encoding="utf-8") as f:
        old_rows = list(csv.DictReader(f))

    migrated = [{field: row.get(field, "") for field in FOLLOWUP_FIELDS} for row in old_rows]

    with open(FOLLOWUP_LOG_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FOLLOWUP_FIELDS)
        writer.writeheader()
        writer.writerows(migrated)


def read_followups() -> list[dict]:
    """Return all follow-up rows as a list of dicts, newest first."""
    if not FOLLOWUP_LOG_PATH.exists():
        return []
    _ensure_followup_header()
    with open(FOLLOWUP_LOG_PATH, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    for row in rows:
        for field in FOLLOWUP_FIELDS:
            if field not in row:
                row[field] = ""
    rows.reverse()
    return rows


def upsert_followup(profile_url: str, **kwargs):
    """
    Insert or update a row in followups.csv by normalized profile_url.
    kwargs are the fields to set/update (e.g. status='replied', replied_at=now).
    """
    _ensure_followup_header()
    norm = _normalize_url_for_log(profile_url)

    rows: list[dict] = []
    found = False

    if FOLLOWUP_LOG_PATH.exists() and FOLLOWUP_LOG_PATH.stat().st_size > 0:
        with open(FOLLOWUP_LOG_PATH, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [{field: row.get(field, "") for field in FOLLOWUP_FIELDS} for row in reader]

    for row in rows:
        if _normalize_url_for_log(row.get("profile_url", "")) == norm:
            for k, v in kwargs.items():
                if k in FOLLOWUP_FIELDS and v:
                    row[k] = v
            found = True
            break

    if not found:
        new_row = {field: "" for field in FOLLOWUP_FIELDS}
        new_row["profile_url"] = profile_url
        for k, v in kwargs.items():
            if k in FOLLOWUP_FIELDS:
                new_row[k] = v
        rows.append(new_row)

    with open(FOLLOWUP_LOG_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FOLLOWUP_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    if _obs:
        try:
            name = kwargs.get("name", "")
            if kwargs.get("follow_up_sent_at") or kwargs.get("status") == "followed_up":
                _obs.on_followup_sent(name=name, profile_url=profile_url)
            elif kwargs.get("status") == "replied" or kwargs.get("replied_at"):
                _obs.on_replied(name=name, profile_url=profile_url)
        except Exception:
            pass


def seed_followups_from_messages():
    """
    On first run: copy any messages.csv rows that aren't already in followups.csv
    into followups.csv with status='pending'.
    """
    _ensure_followup_header()

    # Build set of already-tracked profile URLs
    existing_urls: set[str] = set()
    if FOLLOWUP_LOG_PATH.exists() and FOLLOWUP_LOG_PATH.stat().st_size > 0:
        with open(FOLLOWUP_LOG_PATH, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                u = row.get("profile_url", "")
                if u:
                    existing_urls.add(_normalize_url_for_log(u))

    # Read messages and seed missing ones
    msg_rows = read_messages()  # newest first; we want all of them
    new_rows = []
    for msg in reversed(msg_rows):  # chronological order for append
        url = msg.get("profile_url", "")
        if not url:
            continue
        if _normalize_url_for_log(url) in existing_urls:
            continue
        new_rows.append({
            "profile_url":       url,
            "name":              msg.get("name", ""),
            "role":              msg.get("role", ""),
            "first_msg_sent_at": msg.get("sent_at", ""),
            "follow_up_sent_at": "",
            "replied_at":        "",
            "status":            "pending",
        })
        existing_urls.add(_normalize_url_for_log(url))

    if new_rows:
        with open(FOLLOWUP_LOG_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FOLLOWUP_FIELDS)
            writer.writerows(new_rows)

    return len(new_rows)


def count_followups_pending() -> int:
    """Count rows with status='pending'."""
    if not FOLLOWUP_LOG_PATH.exists():
        return 0
    _ensure_followup_header()
    count = 0
    with open(FOLLOWUP_LOG_PATH, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("status", "") == "pending":
                count += 1
    return count


def count_followups_today() -> int:
    """Count rows where follow_up_sent_at starts with today's date."""
    today = date.today().isoformat()
    if not FOLLOWUP_LOG_PATH.exists():
        return 0
    _ensure_followup_header()
    count = 0
    with open(FOLLOWUP_LOG_PATH, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("follow_up_sent_at", "").startswith(today):
                count += 1
    return count


# ── Analytics: weekly breakdown (Mon–Sun) ────────────────────────────────────

def _week_day_strings() -> list:
    """Return list of 7 ISO date strings for Mon–Sun of the current week."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return [(monday + timedelta(days=i)).isoformat() for i in range(7)]


def weekly_connections_by_day() -> list:
    """Return list of 7 ints: connection requests sent each day Mon–Sun."""
    days = _week_day_strings()
    counts = [0] * 7
    if not LOG_PATH.exists():
        return counts
    _ensure_header()
    with open(LOG_PATH, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = row.get("sent_at", "")[:10]
            if d in days:
                counts[days.index(d)] += 1
    return counts


def weekly_messages_by_day() -> list:
    """Return list of 7 ints: first messages sent each day Mon–Sun."""
    days = _week_day_strings()
    counts = [0] * 7
    if not MSG_LOG_PATH.exists():
        return counts
    _ensure_msg_header()
    with open(MSG_LOG_PATH, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = row.get("sent_at", "")[:10]
            if d in days:
                counts[days.index(d)] += 1
    return counts


def weekly_followups_by_day() -> list:
    """Return list of 7 ints: follow-ups sent each day Mon–Sun."""
    days = _week_day_strings()
    counts = [0] * 7
    if not FOLLOWUP_LOG_PATH.exists():
        return counts
    _ensure_followup_header()
    with open(FOLLOWUP_LOG_PATH, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = row.get("follow_up_sent_at", "")[:10]
            if d in days:
                counts[days.index(d)] += 1
    return counts


# ── Analytics: quarterly totals ───────────────────────────────────────────────

def _quarter_bounds() -> tuple:
    """Return (start_iso, end_iso) for the current calendar quarter."""
    today = date.today()
    q_start_month = ((today.month - 1) // 3) * 3 + 1
    q_start = date(today.year, q_start_month, 1)
    if q_start_month + 3 > 12:
        q_end = date(today.year + 1, 1, 1)
    else:
        q_end = date(today.year, q_start_month + 3, 1)
    return q_start.isoformat(), q_end.isoformat()


def quarterly_connections_sent() -> int:
    """Count connection requests sent this quarter."""
    q_start, q_end = _quarter_bounds()
    if not LOG_PATH.exists():
        return 0
    _ensure_header()
    count = 0
    with open(LOG_PATH, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = row.get("sent_at", "")[:10]
            if q_start <= d < q_end:
                count += 1
    return count


def quarterly_messages_sent() -> int:
    """Count first messages sent this quarter."""
    q_start, q_end = _quarter_bounds()
    if not MSG_LOG_PATH.exists():
        return 0
    _ensure_msg_header()
    count = 0
    with open(MSG_LOG_PATH, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = row.get("sent_at", "")[:10]
            if q_start <= d < q_end:
                count += 1
    return count


def quarterly_followups_sent() -> int:
    """Count follow-ups sent this quarter."""
    q_start, q_end = _quarter_bounds()
    if not FOLLOWUP_LOG_PATH.exists():
        return 0
    _ensure_followup_header()
    count = 0
    with open(FOLLOWUP_LOG_PATH, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = row.get("follow_up_sent_at", "")[:10]
            if q_start <= d < q_end and row.get("follow_up_sent_at", ""):
                count += 1
    return count


def quarterly_connections_accepted() -> int:
    """
    Return the persisted accepted-connections count.
    Starts at ACCEPTED_BASELINE (15) until the user triggers a LinkedIn scrape,
    which writes the real count to accepted_count.txt via set_accepted_count().
    """
    if _ACCEPTED_COUNT_PATH.exists():
        try:
            return int(_ACCEPTED_COUNT_PATH.read_text().strip())
        except ValueError:
            pass
    return ACCEPTED_BASELINE


def set_accepted_count(count: int) -> None:
    """Persist the accepted-connections count returned by a LinkedIn scrape."""
    _ACCEPTED_COUNT_PATH.write_text(str(count))
