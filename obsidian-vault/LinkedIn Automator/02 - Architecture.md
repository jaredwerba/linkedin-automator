---
tags: [linkedin-automator, architecture]
created: 2026-02-21
---

# ⚙️ Architecture

← [[00 - Home]]

---

## System Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    Browser (UI)                          │
│              http://localhost:8000                       │
│                                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │Live Feed │ │ Results  │ │Msg Prosp.│ │Follow Up │  │
│  └────┬─────┘ └──────────┘ └────┬─────┘ └────┬─────┘  │
│       │ WebSocket /ws            │ /ws/msg     │/ws/followup
└───────┼──────────────────────────┼─────────────┼────────┘
        │                          │             │
┌───────▼──────────────────────────▼─────────────▼────────┐
│                    FastAPI (main.py)                      │
│                                                          │
│  GET /status  GET /results  GET /messages  GET /followups│
│  GET /runs    GET /msg-status  GET /followup-status      │
│  POST /test-ai                                           │
└───────────────┬──────────────┬──────────────┬───────────┘
                │              │              │
        ┌───────▼───┐  ┌───────▼───┐  ┌──────▼──────┐
        │automator  │  │messenger  │  │  logger.py  │
        │   .py     │  │   .py     │  │             │
        │(connects) │  │(messages+ │  │connections  │
        └─────┬─────┘  │ followups)│  │messages     │
              │        └─────┬─────┘  │followups    │
              │              │        │  (CSVs)     │
        ┌─────▼──────────────▼──────┐ └─────────────┘
        │   Playwright Chrome       │
        │  (persistent context)     │
        │                           │
        │   Your LinkedIn Session   │
        └───────────────────────────┘
                      │
              ┌───────▼───────┐
              │  ai.py        │
              │  Ollama local │
              │  or Gemini    │
              └───────────────┘
```

---

## Request Flow — Connection Run

```
User clicks Execute
  → app.js opens WebSocket /ws
  → main.py receives {action: "run", companies: [...]}
  → automator.run() launches Chrome
  → Searches LinkedIn for people at each company
  → Scores each profile (AI or keyword)
  → Sends connection request with note
  → Logs to connections.csv
  → Streams log messages back via WebSocket
  → UI renders in Live Feed
```

## Request Flow — First Message Run

```
User clicks Send Messages (Msg Prospect tab)
  → app.js opens WebSocket /ws/msg
  → main.py receives {action: "msg_run", msg_cap: N}
  → messenger.run_messaging() launches Chrome
  → Navigates to /mynetwork/invite-connect/connections/
  → JS evaluates DOM → scrapes connection cards
  → Filters already-messaged (dedup via messages.csv)
  → For each new connection:
      → navigate to compose URL
      → Ollama generates personalized message
      → Types message, clicks Send
      → Logs to messages.csv
      → Seeds followups.csv (status=pending)
```

## Request Flow — Follow-Up Run

```
User clicks Send Follow-Ups (Follow Up tab)
  → app.js opens WebSocket /ws/followup
  → main.py receives {action: "followup_run", wait_days: N}
  → messenger.run_followups() launches Chrome
  → Seeds followups.csv from messages.csv (idempotent)
  → Filters: status=pending AND first_msg_sent_at ≤ cutoff
  → For each candidate:
      → Navigate to their LinkedIn profile page
      → Click the Message <button> on the profile
      → Compose overlay opens on the profile page
      → Check last message bubble class:
          .msg-s-event-listitem--other → they replied → mark replied, skip
          .msg-s-event-listitem--self  → we sent last → send follow-up
      → Ollama generates follow-up referencing original message
      → Types message, clicks Send
      → upsert_followup() → status=followed_up
```

---

## WebSocket Message Protocol

All WebSocket channels use the same JSON message format:

```json
// Server → Client
{ "type": "log",     "message": "Navigating to profile..." }
{ "type": "started"                                         }
{ "type": "done"                                            }
{ "type": "error",   "message": "Something went wrong"     }

// Client → Server
{ "action": "run",          "companies": [...], "speed_multiplier": 1.0 }
{ "action": "msg_run",      "msg_cap": 5, "scan_limit": 20              }
{ "action": "followup_run", "followup_cap": 5, "wait_days": 3           }
{ "action": "pause"  }
{ "action": "resume" }
{ "action": "stop"   }
```

---

## Deduplication Strategy

| Feature | Dedup Key | Storage |
|---------|-----------|---------|
| Connection requests | `profile_url` (normalized) | `connections.csv` |
| First messages | `profile_url` + name fallback | `messages.csv` |
| Follow-ups | `status != "pending"` | `followups.csv` |

URL normalization: strips query params, trailing slash, lowercased.
