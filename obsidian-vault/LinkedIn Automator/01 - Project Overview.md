---
tags: [linkedin-automator, overview]
created: 2026-02-21
---

# 📋 Project Overview

← [[00 - Home]]

---

## What It Does

LinkedIn Automator is a **personal cold outreach tool** that runs entirely on your local machine. It reuses your existing Chrome login session to operate LinkedIn as you would — no headless scraping, no unofficial APIs.

It handles three phases of the outreach funnel automatically:

```
1. Find decision makers at target companies
        ↓
2. Send AI-personalized connection request notes
        ↓
3. Send AI-personalized first messages to new connections
        ↓
4. Detect replies — send AI-personalized follow-up if silent
```

---

## Tech Stack

| Layer | Technology | Role |
|-------|-----------|------|
| **Backend** | Python + FastAPI | API server, WebSocket streaming |
| **Browser** | Playwright (Chromium) | LinkedIn automation via persistent Chrome context |
| **AI** | Ollama (`llama3.1:8b`) or Gemini | Message generation |
| **Frontend** | Vanilla JS + CSS | Single-page dashboard UI |
| **Data** | CSV files | Logging, dedup, follow-up tracking |
| **Realtime** | WebSockets | Live log streaming to UI |

---

## File Map

```
linkedin-automator/
├── main.py           # FastAPI app — all HTTP + WebSocket endpoints
├── automator.py      # Connection request automation (core Playwright logic)
├── messenger.py      # Messaging + follow-up automation
├── logger.py         # All CSV read/write (connections, messages, followups)
├── ai.py             # Ollama + Gemini wrappers
├── run_logger.py     # Per-run history logging
├── .env              # Config (AI provider, caps, Chrome path)
│
├── static/
│   ├── index.html    # Dashboard UI
│   ├── app.js        # All frontend JS
│   └── style.css     # Styling
│
├── connections.csv   # Log of all connection requests sent
├── messages.csv      # Log of all first messages sent
├── followups.csv     # Follow-up tracker with status per person
│
├── messenger_debug.log  # Verbose step-by-step automation log
└── obsidian-vault/      # This documentation
```

---

## Key Design Decisions

> [!important] Persistent Chrome Context
> The tool uses `launch_persistent_context()` which reuses your real Chrome profile. LinkedIn sees it as your normal browser session — not automation. This is the primary reason it works without triggering bot detection.

> [!note] No Headless Mode
> Chrome runs visibly. You can watch every action in real time and stop anything with the Stop button.

> [!tip] Local AI Only (default)
> By default, Ollama runs models locally. Your outreach data and message content never leave your machine.
