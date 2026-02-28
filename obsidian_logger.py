"""
Obsidian integration via the Local REST API plugin.

Writes/updates one Markdown note per prospect in the vault's Prospects/ folder.
Gracefully no-ops if Obsidian is not running or the plugin is not installed.

Setup (one-time):
  1. Open Obsidian → Settings → Community Plugins → Browse → "Local REST API"
  2. Install + Enable it
  3. Copy the API key from the plugin settings into .env as OBSIDIAN_API_KEY
  4. Ensure OBSIDIAN_VAULT_PATH in .env points at your vault root

The plugin listens on https://localhost:27124 (HTTPS) or http://localhost:27123 (HTTP).
We use HTTP by default to avoid self-signed cert issues.
"""

import os
import re
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

OBSIDIAN_API_KEY   = os.getenv("OBSIDIAN_API_KEY", "")
OBSIDIAN_BASE_URL  = os.getenv("OBSIDIAN_BASE_URL", "http://localhost:27123")
OBSIDIAN_VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "")  # absolute path to vault root
PROSPECTS_FOLDER   = os.getenv("OBSIDIAN_PROSPECTS_FOLDER", "Prospects")

_ENABLED = bool(OBSIDIAN_API_KEY and OBSIDIAN_BASE_URL)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_filename(name: str) -> str:
    """Convert a person's name to a safe filename (no special chars)."""
    clean = re.sub(r'[\\/:*?"<>|]', '', name).strip()
    return clean or "Unknown"


def _note_path(name: str) -> str:
    """Return the vault-relative path for a prospect note."""
    return f"{PROSPECTS_FOLDER}/{_safe_filename(name)}.md"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {OBSIDIAN_API_KEY}",
        "Content-Type": "text/markdown",
    }


def _get_note(note_path: str) -> str | None:
    """Fetch existing note content. Returns None if not found or Obsidian is down."""
    if not _ENABLED:
        return None
    try:
        url = f"{OBSIDIAN_BASE_URL}/vault/{requests.utils.quote(note_path, safe='/')}"
        resp = requests.get(url, headers=_headers(), timeout=3)
        if resp.status_code == 200:
            return resp.text
        return None
    except Exception:
        return None


def _put_note(note_path: str, content: str) -> bool:
    """Write (create or overwrite) a note. Returns True on success."""
    if not _ENABLED:
        return False
    try:
        url = f"{OBSIDIAN_BASE_URL}/vault/{requests.utils.quote(note_path, safe='/')}"
        resp = requests.put(url, headers=_headers(), data=content.encode("utf-8"), timeout=3)
        return resp.status_code in (200, 201, 204)
    except Exception:
        return False


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ── Note builder ───────────────────────────────────────────────────────────────

def _build_new_note(name: str, role: str, company: str, profile_url: str,
                    score: str, scorer: str, note: str) -> str:
    """Create a fresh prospect note."""
    company_link = f"[[{company}]]" if company else "—"
    score_str    = f"{score}/10 ({scorer})" if score else "—"
    lines = [
        f"# {name}",
        f"",
        f"**Company:** {company_link}  ",
        f"**Role:** {role or '—'}  ",
        f"**Profile:** {profile_url or '—'}  ",
        f"**Score:** {score_str}  ",
        f"",
        f"---",
        f"",
        f"## Timeline",
        f"",
        f"- {_now()}  Connection request sent",
    ]
    if note:
        lines += [
            f"",
            f"## Connection Note",
            f"",
            f"> {note}",
        ]
    lines += [
        f"",
        f"## Notes",
        f"",
        f"",
        f"---",
        f"",
        f"Tags: #pipeline/connected #{_tag(company)}",
    ]
    return "\n".join(lines)


def _tag(text: str) -> str:
    """Convert a company name to a safe Obsidian tag."""
    return re.sub(r"[^a-zA-Z0-9]", "-", text).strip("-").lower() if text else "unknown"


def _append_timeline(existing: str, event: str) -> str:
    """Append a timestamped line to the Timeline section of an existing note."""
    line = f"- {_now()}  {event}"
    if "## Timeline" in existing:
        # Insert after the last existing timeline bullet, or after the header
        parts = existing.split("## Timeline")
        before = parts[0] + "## Timeline"
        after  = parts[1]
        # Find the end of the existing timeline bullets
        after_lines = after.split("\n")
        insert_at = 0
        for i, l in enumerate(after_lines):
            if l.strip().startswith("- "):
                insert_at = i
        after_lines.insert(insert_at + 1, line)
        return before + "\n".join(after_lines)
    else:
        # No timeline section — append at end
        return existing.rstrip() + f"\n\n## Timeline\n\n{line}\n"


def _update_tags(existing: str, new_tag: str) -> str:
    """Replace the pipeline stage tag."""
    # Swap #pipeline/xxx for the new tag
    return re.sub(r"#pipeline/\S+", f"#pipeline/{new_tag}", existing)


# ── Public API ─────────────────────────────────────────────────────────────────

def on_connection_sent(name: str, role: str, company: str, profile_url: str,
                       score: int, scorer: str, note: str = "") -> None:
    """
    Called after log_connection() — creates a new prospect note or appends
    a timeline event if the note already exists.
    """
    if not _ENABLED:
        return
    path     = _note_path(name)
    existing = _get_note(path)
    if existing:
        updated = _append_timeline(existing, "Connection request sent")
        _put_note(path, updated)
    else:
        content = _build_new_note(name, role, company, profile_url,
                                  str(score), scorer, note)
        _put_note(path, content)


def on_message_sent(name: str, role: str, profile_url: str, message: str) -> None:
    """
    Called after log_message() — appends message event + message text to note.
    """
    if not _ENABLED:
        return
    path     = _note_path(name)
    existing = _get_note(path)
    if existing:
        updated = _append_timeline(existing, "First message sent")
        # Append message text under its own section if not already there
        if "## First Message" not in updated:
            updated = updated.rstrip() + f"\n\n## First Message\n\n> {message}\n"
        updated = _update_tags(updated, "messaged")
        _put_note(path, updated)
    else:
        # Note doesn't exist yet — create a minimal one
        lines = [
            f"# {name}",
            f"",
            f"**Role:** {role or '—'}  ",
            f"**Profile:** {profile_url or '—'}  ",
            f"",
            f"---",
            f"",
            f"## Timeline",
            f"",
            f"- {_now()}  First message sent",
            f"",
            f"## First Message",
            f"",
            f"> {message}",
            f"",
            f"## Notes",
            f"",
            f"",
            f"---",
            f"",
            f"Tags: #pipeline/messaged",
        ]
        _put_note(path, "\n".join(lines))


def on_followup_sent(name: str, profile_url: str) -> None:
    """Called after a follow-up is sent — appends timeline event."""
    if not _ENABLED:
        return
    path     = _note_path(name)
    existing = _get_note(path)
    if existing:
        updated = _append_timeline(existing, "Follow-up sent")
        updated = _update_tags(updated, "followed-up")
        _put_note(path, updated)


def on_replied(name: str, profile_url: str) -> None:
    """Called when a reply is detected — updates stage tag."""
    if not _ENABLED:
        return
    path     = _note_path(name)
    existing = _get_note(path)
    if existing:
        updated = _append_timeline(existing, "Replied")
        updated = _update_tags(updated, "replied")
        _put_note(path, updated)


def on_post_liked(name: str, profile_url: str, liked: bool) -> None:
    """Called after creep mode visits a profile."""
    if not _ENABLED:
        return
    path     = _note_path(name)
    existing = _get_note(path)
    if existing:
        event   = "Post liked (Creep Mode)" if liked else "Profile visited — no post available"
        updated = _append_timeline(existing, event)
        _put_note(path, updated)


def on_connection_accepted(name: str, role: str, company: str,
                           profile_url: str, connected_date: str = "") -> None:
    """
    Called during the LinkedIn connections scrape (refresh-accepted).
    Creates a new Obsidian note tagged #pipeline/accepted, or updates an existing
    note (created when the connection request was sent) to the accepted stage.
    """
    if not _ENABLED:
        return
    path     = _note_path(name)
    existing = _get_note(path)
    date_label = connected_date or _now()[:10]
    if existing:
        updated = _append_timeline(existing, f"Connection accepted ({date_label})")
        updated = _update_tags(updated, "accepted")
        _put_note(path, updated)
    else:
        company_link = f"[[{company}]]" if company else "—"
        lines = [
            f"# {name}",
            f"",
            f"**Company:** {company_link}  ",
            f"**Role:** {role or '—'}  ",
            f"**Profile:** {profile_url or '—'}  ",
            f"",
            f"---",
            f"",
            f"## Timeline",
            f"",
            f"- {date_label}  Connection accepted",
            f"",
            f"## Notes",
            f"",
            f"",
            f"---",
            f"",
            f"Tags: #pipeline/accepted #{_tag(company)}",
        ]
        _put_note(path, "\n".join(lines))


def is_enabled() -> bool:
    """Returns True if Obsidian integration is configured and reachable."""
    if not _ENABLED:
        return False
    try:
        resp = requests.get(f"{OBSIDIAN_BASE_URL}/", headers=_headers(), timeout=2)
        return resp.status_code < 500
    except Exception:
        return False
