---
tags: [linkedin-automator, features]
created: 2026-02-21
---

# 🚀 Features

← [[00 - Home]]

---

## Feature 1 — Connection Automation

**Tab:** Live Feed (left panel → Execute button)

Finds decision makers at target companies and sends personalized connection requests.

### How it works
1. Enter target company names (one per line) in the left panel
2. Click **Execute**
3. Chrome opens, searches LinkedIn for people at each company
4. Each profile is scored (AI or keyword matching)
5. Connection request sent with an AI-written note
6. Logged to `connections.csv`

### Controls
| Control | Purpose |
|---------|---------|
| Action Delay slider | DEMO / FAST / NORMAL / SAFE — controls time between actions |
| Pause button | Suspends after current action |
| Stop button | Cancels run cleanly |
| Test AI button | Verifies Ollama/Gemini is reachable |

### Caps & Limits
- `DAILY_CAP=20` in `.env` — max connection requests per day
- `WEEKLY_CAP=100` — tracked in the ring widget
- Configurable via `.env`

### Ring Widget
Three concentric arcs show:
- **Outer ring** — weekly connections (vs 100 cap)
- **Middle ring** — today's connections (vs daily cap)
- **Inner ring** — connections sent with a message note

---

## Feature 2 — First Message (Msg Prospect)

**Tab:** Msg Prospect

Sends AI-personalized first messages to new connections who haven't been messaged yet.

### How it works
1. Click the **Msg Prospect** tab
2. Set **Messages per Run** slider (1–10)
3. Click **Send Messages**
4. Chrome opens, navigates to connections page
5. Scrapes visible connection cards via JavaScript DOM evaluation
6. Filters out anyone already in `messages.csv`
7. For each new connection:
   - Navigates directly to their compose URL
   - Ollama generates a warm, non-salesy first message
   - Types message and clicks Send
   - Logs to `messages.csv`
   - Seeds `followups.csv` with `status=pending`

### Message Prompt Design
```
Write a short, friendly LinkedIn first message to {first_name},
who just connected with me. Their role is: {role}.
Rules:
- 2-3 sentences max
- Warm and genuine, not salesy
- Reference their role if known
- Do NOT mention jobs, recruiting, or opportunities
- Start with 'Hi {first_name}'
- Return ONLY the message text
```

### Dedup Logic
- Primary: normalized `profile_url` match against `messages.csv`
- Fallback: lowercased `name` match (for manually-added rows)

---

## Feature 3 — Follow-Up Sequence with Reply Detection

**Tab:** Follow Up

Sends a single gentle follow-up to connections who haven't replied after a set number of days.

### How it works
1. Click the **Follow Up** tab
2. Set **Wait before follow-up** slider (0 = test mode, 1–14 days)
3. Set **Follow-ups per Run** slider (1–10)
4. Click **Send Follow-Ups**
5. `followups.csv` is seeded from `messages.csv` (idempotent — safe to run repeatedly)
6. Filters to: `status = pending` AND `first_msg_sent_at ≤ now - wait_days`
7. For each candidate:
   - Navigates to their LinkedIn profile page
   - Clicks the **Message button** directly on the profile
   - Compose overlay opens on top of the profile (no page jump)
   - Checks last message bubble class to detect reply
   - If replied → marks `status=replied`, moves on
   - If not replied → Ollama generates follow-up → types → Send
   - Updates `followups.csv` → `status=followed_up`

### Reply Detection
```
DOM selectors checked inside the open compose overlay:
  .msg-s-event-listitem--other  →  they sent last  →  replied ✓
  .msg-s-event-listitem--self   →  we sent last    →  no reply
  (none found)                  →  unknown         →  treat as no reply
```

### Status Values in followups.csv
| Status | Meaning |
|--------|---------|
| `pending` | First message sent, no follow-up yet |
| `replied` | They replied — no follow-up needed |
| `followed_up` | Follow-up sent |
| `done` | Reserved for future use |

### Follow-Up Prompt Design
```
Write a short, gentle follow-up LinkedIn message to {first_name},
a {role}, who hasn't replied yet.
My original message was: "{original_message[:120]}"
Rules:
- 1-2 sentences max
- Warm, not pushy
- Do NOT mention jobs, recruiting, or opportunities
- Do NOT repeat the original message verbatim
- Start with 'Hi {first_name}'
- Return ONLY the message text
```

> [!note] One Follow-Up Only
> The system sends exactly one follow-up per connection. Once `status=followed_up`, that person is never contacted again automatically.

---

## Common Behaviors Across All Features

### 5-Second Send Countdown
Before every send (first message or follow-up), the live feed shows:
```
Sending in 5s — click Stop to cancel...
```
This gives you a window to abort any individual message.

### CAPTCHA Detection
If LinkedIn shows a CAPTCHA at any point, the run pauses and logs a warning. You solve it manually, then restart.

### Speed Modes
| Mode | Delay between actions |
|------|-----------------------|
| DEMO | ~1s (high risk) |
| FAST | ~3–5s |
| NORMAL | ~5–8s |
| SAFE | 8–15s (recommended) |

### AI Quote Stripping
Both message generators apply `.strip().strip('"').strip("'")` to remove any quote characters the AI wraps around its output.
