---
tags: [linkedin-automator, setup, configuration]
created: 2026-02-21
---

# 🔧 Configuration & Setup

← [[00 - Home]]

---

## Prerequisites

- Python 3.11+
- Google Chrome installed
- [Ollama](https://ollama.ai) running locally (or Gemini API key)
- LinkedIn account (logged in via Chrome)

---

## Installation

```bash
cd ~/LI/linkedin-automator
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

---

## .env Reference

```ini
# AI Provider: "ollama" or "gemini"
AI_PROVIDER=ollama

# Ollama settings
OLLAMA_MODEL=llama3.1:8b
OLLAMA_BASE_URL=http://localhost:11434

# Gemini settings (if using Gemini)
GEMINI_MODEL=gemini-2.0-flash-exp
GEMINI_API_KEY=your_key_here

# LinkedIn caps
DAILY_CAP=20
DEMO_CAP=3
TOTAL_HOURS=10

# Chrome profile (auto-detected if blank)
CHROME_PROFILE_PATH=/Users/jkw/Library/Application Support/Google/ChromeLinkedIn

# Fuzzy match threshold for company search (0-100)
FUZZY_MATCH_THRESHOLD=80
```

> [!warning] Chrome Profile
> The Chrome profile at `CHROME_PROFILE_PATH` must be logged into LinkedIn. The tool will fail silently if Chrome opens to a login page.

---

## Starting the Server

```bash
cd ~/LI/linkedin-automator
source venv/bin/activate
uvicorn main:app --reload --port 8000
```

Then open **http://localhost:8000** in your browser.

---

## AI Provider Setup

### Option A — Ollama (local, recommended)

```bash
# Install Ollama
brew install ollama   # macOS

# Pull the model
ollama pull llama3.1:8b

# Start Ollama (auto-starts on macOS)
ollama serve
```

Test via the **Test AI** button in the dashboard.

### Option B — Gemini

1. Get API key from [Google AI Studio](https://aistudio.google.com)
2. Set in `.env`:
   ```ini
   AI_PROVIDER=gemini
   GEMINI_API_KEY=your_key_here
   ```
3. No local model needed

---

## Chrome Profile Setup

The tool needs a dedicated Chrome profile that's logged into LinkedIn.

```bash
# Create a dedicated profile (run this once)
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --user-data-dir="/Users/jkw/Library/Application Support/Google/ChromeLinkedIn" \
  --no-first-run
```

Log into LinkedIn in that Chrome window, then close it. The tool will reuse the session.

---

## Speed Mode Recommendations

| Situation | Recommended Mode |
|-----------|-----------------|
| Testing / verifying selectors | DEMO |
| Trusted network, low volume | FAST |
| Daily use, normal volume | NORMAL |
| Staying under LinkedIn radar | SAFE |

> [!caution] LinkedIn Rate Limits
> LinkedIn will restrict your account if you send too many requests too quickly. Use **SAFE** mode for production runs. Never exceed ~20 connections/day or ~5 messages/hour.

---

## Data Files

All data is stored locally. Never committed to git (`*.csv` in `.gitignore`).

| File | Purpose | Safe to edit manually? |
|------|---------|----------------------|
| `connections.csv` | Connection request log | ✅ Yes |
| `messages.csv` | First message log | ✅ Yes (add manual rows) |
| `followups.csv` | Follow-up tracker | ✅ Yes (edit status/dates) |
| `messenger_debug.log` | Verbose automation log | Read-only |

### Manually adding a row to messages.csv
If you messaged someone outside the tool:
```csv
2026-02-20 16:00,Marissa,,,Message sent manually — logged to prevent duplicate outreach.
```
The dedup system will then skip them automatically.
