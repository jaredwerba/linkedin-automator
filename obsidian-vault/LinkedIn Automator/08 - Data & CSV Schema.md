---
tags: [linkedin-automator, data, schema]
created: 2026-02-21
---

# 📊 Data & CSV Schema

← [[00 - Home]]

---

## connections.csv

Logs every connection request sent.

| Field | Type | Example |
|-------|------|---------|
| `sent_at` | datetime | `2026-02-20 15:26` |
| `name` | string | `Tomer Fuss Sanderovich` |
| `role` | string | `CPO @ Natural Intelligence` |
| `company` | string | `Natural Intelligence` |
| `profile_url` | string | `https://linkedin.com/in/tomer-...` |
| `score` | int | `85` |
| `scorer` | string | `AI` or `keywords` |
| `note` | string | Connection note text sent |

**Used for:** deduplication (don't connect twice), ring widget counts, Results tab table.

---

## messages.csv

Logs every first message sent.

| Field | Type | Example |
|-------|------|---------|
| `sent_at` | datetime | `2026-02-20 15:26` |
| `name` | string | `Tomer Fuss Sanderovich` |
| `role` | string | `CPO @ Natural Intelligence` |
| `profile_url` | string | `https://linkedin.com/in/tomer-...` |
| `message` | string | Full message text sent |

**Used for:**
- Dedup in Msg Prospect (skip if profile_url already logged)
- Seed source for `followups.csv`
- Original message reference for follow-up AI prompt
- Msg Prospect tab table

**Manual entries:** You can add rows manually to prevent the tool from messaging someone you've already contacted outside the tool. Set `profile_url` correctly for dedup to work; leave `message` blank or add a note.

---

## followups.csv

Tracks the full follow-up lifecycle per connection.

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `profile_url` | string | `https://linkedin.com/in/tomer-...` | Primary key (normalized) |
| `name` | string | `Tomer Fuss Sanderovich` | |
| `role` | string | `CPO @ Natural Intelligence` | |
| `first_msg_sent_at` | datetime | `2026-02-20 15:26` | Copied from messages.csv |
| `follow_up_sent_at` | datetime | `2026-02-21 13:57` | Set when follow-up sent |
| `replied_at` | datetime | `` | Set when reply detected |
| `status` | string | `followed_up` | See below |

### Status Values

```
pending      → first message sent, no follow-up yet
replied      → they replied (reply detected in thread)
followed_up  → follow-up sent, waiting
done         → reserved for future use
```

### How followups.csv is populated

1. **Auto-seeded** from `messages.csv` each time a follow-up run starts (`seed_followups_from_messages` — idempotent)
2. **Updated** by `upsert_followup()` which matches on normalized `profile_url` and updates fields in-place

### Manually editing followups.csv

You can freely edit the file:
- Change `status` back to `pending` to re-trigger a follow-up
- Set `first_msg_sent_at` to an older date to test timing logic
- Set `status=replied` to prevent follow-up to someone who replied outside LinkedIn

---

## URL Normalization

All profile URLs are normalized before comparison:
```python
url.split("?")[0].rstrip("/").lower()

# Example:
# https://www.linkedin.com/in/tomer-fuss-sanderovich/?lipi=xyz
# → https://www.linkedin.com/in/tomer-fuss-sanderovich
```

This ensures dedup works regardless of tracking parameters LinkedIn adds to URLs.

---

## Data Privacy

> [!important] Your data stays local
> - All CSV files are in `.gitignore` (`*.csv`) — never committed
> - Log files are in `.gitignore` (`*.log`) — never committed
> - No analytics, no telemetry, no cloud sync
> - If using Ollama: message content never leaves your machine
> - If using Gemini: message prompts are sent to Google's API
