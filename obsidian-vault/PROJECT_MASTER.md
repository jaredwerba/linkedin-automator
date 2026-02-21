# LinkedIn Automator — Complete Project Master Document
**Last Updated:** 2026-02-21
**Purpose:** Full disaster-recovery context document. If a Claude session ends, paste this into a new session and work continues immediately with zero loss of context.

---

## 0. HOW TO USE THIS DOCUMENT (for new Claude session)

Read this entire document before touching any code. Then run:
```bash
cd /Users/jkw/LI/linkedin-automator
source venv/bin/activate
uvicorn main:app --reload --port 8000
```
Open `http://localhost:8000` in browser. You are now running the app.

All file paths in this document are **absolute**. Use them directly with the Read tool.

---

## 1. WHAT THIS PROJECT IS

A **LinkedIn outreach automation tool** built for personal sales/BD use. It runs as a local web app. The user opens a browser at `localhost:8000`, types in target company names, and the tool:

1. Searches LinkedIn for each company
2. Finds the People tab
3. AI-scores each person's title for relevance as a cloud infrastructure decision-maker
4. Sends connection requests (with AI-written personalized notes) to the top-ranked people
5. Later: sends first messages to accepted connections via the Msg Prospect tab
6. Later: sends follow-ups to people who haven't replied via the Follow Up tab

The entire thing runs locally. No cloud backend. No database. Flat CSV files for storage.

**The user's target persona:** Cloud infrastructure decision-makers (CTOs, VPs of Engineering, Directors of Platform/Cloud, etc.) at specific companies the user designates.

---

## 2. TECH STACK

### Backend
| Component | Technology | Version |
|-----------|-----------|---------|
| Web framework | FastAPI | 0.115.6 |
| ASGI server | uvicorn[standard] | 0.32.1 |
| Browser automation | Playwright (async) | 1.50.0 |
| AI — local | Ollama (llama3.1:8b default) | 0.4.4 |
| AI — cloud | Google Gemini (gemini-2.0-flash-exp) | via google-generativeai 0.8.3 |
| Fuzzy matching | fuzzywuzzy + python-Levenshtein | 0.18.0 / 0.27.1 |
| Env config | python-dotenv | 1.0.1 |
| Real-time comms | WebSockets | 14.1 |

### Frontend
| Component | Technology |
|-----------|-----------|
| HTML | Vanilla (no framework) |
| CSS | Hand-crafted, CRT/terminal aesthetic |
| JS | Vanilla ES2023 (no build step, no bundler) |
| Font | Share Tech Mono (Google Fonts) |
| Charts | SVG (hand-coded ring widget) |

### Storage (all flat files, same directory as main.py)
| File | Format | Purpose |
|------|--------|---------|
| `connections.csv` | CSV | Every connection request sent |
| `messages.csv` | CSV | Every first message sent |
| `followups.csv` | CSV | Follow-up tracking (pending/replied/followed_up) |
| `runs.jsonl` | JSONL | Per-run history (log entries, companies, totals) |
| `accepted_count.txt` | Plain text (integer) | Persisted accepted-connections count |
| `.env` | Key=value | API keys, caps, Chrome path |
| `messenger_debug.log` | Log file | Debug log for messenger.py |

### Python venv
```
/Users/jkw/LI/linkedin-automator/venv/
```
Activate: `source /Users/jkw/LI/linkedin-automator/venv/bin/activate`

---

## 3. DIRECTORY STRUCTURE

```
/Users/jkw/LI/linkedin-automator/
├── main.py              # FastAPI app, all HTTP routes + WebSocket endpoints
├── automator.py         # Connection request automation (Playwright)
├── messenger.py         # Messaging + follow-up automation (Playwright)
├── ai.py                # AI title scoring + note/message generation
├── logger.py            # CSV read/write + analytics aggregation
├── run_logger.py        # Per-run history (JSONL)
├── requirements.txt     # Python dependencies
├── .env                 # Local config (NOT in git)
├── connections.csv      # Data: connection requests sent
├── messages.csv         # Data: messages sent
├── followups.csv        # Data: follow-up tracking
├── runs.jsonl           # Data: run history
├── accepted_count.txt   # Data: accepted connections count (currently: 15)
├── messenger_debug.log  # Debug log for messenger.py
├── static/
│   ├── index.html       # Single-page app shell
│   ├── app.js           # All frontend logic (~1,100 lines)
│   └── style.css        # All styles (~1,200+ lines, CRT theme)
├── obsidian-vault/
│   └── PROJECT_MASTER.md  ← THIS FILE
└── venv/                # Python virtual environment
```

---

## 4. HOW TO RUN

### Start the server
```bash
cd /Users/jkw/LI/linkedin-automator
source venv/bin/activate
uvicorn main:app --reload --port 8000
```

### Access the UI
```
http://localhost:8000
```

### Environment Variables (`.env` file)
```env
# AI provider: "ollama" or "gemini"
AI_PROVIDER=ollama
OLLAMA_MODEL=llama3.1:8b
OLLAMA_BASE_URL=http://localhost:11434

# For Gemini (if AI_PROVIDER=gemini):
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.0-flash-exp

# LinkedIn caps (safety limits)
DAILY_CAP=30        # max connection requests per day
WEEKLY_CAP=100      # max connection requests per Mon-Sun week
DEMO_CAP=3          # max connections per company per run

# Chrome (auto-detected if not set)
CHROME_PROFILE_PATH=/Users/jkw/Library/Application Support/Google/ChromeLinkedIn
```

### If using Ollama
```bash
ollama serve          # must be running in background
ollama pull llama3.1:8b
```

---

## 5. GIT STATE

### Branch
```
visual-updates
```
Tracked remote: `origin/visual-updates`

### Current status (as of 2026-02-21)
```
modified: static/index.html   (unstaged — minor diff from weekly chart deletion)
```
Everything else is committed and clean.

### Milestone tag
```
v1.0-milestone
```
Created on commit `2a81b2b` ("weekly analytics"). This is the stable recovery point.

### To restore to milestone
```bash
git checkout v1.0-milestone
```
Note: The v1.0-milestone tag was created at the end of a productive session. It includes all the analytics, quarterly scorecard, score sorting, and follow-up features. The weekly bar chart code (which was later deleted) is also in that tagged commit but can be ignored — the current branch HEAD has it properly removed.

### Recent commit log
```
2a81b2b  weekly analytics              ← v1.0-milestone tag here
e8730bb  messaging follow up
650ade1  follow up
c2e49d5  final messaging changes
da3d9e6  Merge branch 'messaging'
bd8d3a7  messaging restored
3a2d09b  messaging feature
6299b3a  messaging feature
b04c732  timer slider
964b3a0  initial commit
```

---

## 6. ARCHITECTURE DEEP DIVE

### 6.1 Connection Flow (the main automation)

```
User fills companies textarea → clicks Execute
  ↓
app.js: startRun() opens WebSocket to /ws
  ↓
main.py: /ws endpoint accepts, receives JSON {action:"run", companies:[...], speed_multiplier:float}
  ↓
asyncio.Task: automator.run_automation(company_list, log_fn, speed_multiplier)
  ↓
For each company:
  1. _find_company_page() — LinkedIn company search + fuzzy match
  2. _go_to_people_tab() — navigate to /people/ URL
  3. _scrape_people_cards() — DOM scrape, AI score each title
  4. Sort by score (highest first)
  5. For each person up to DEMO_CAP:
      _send_connection() → Strategy 1 (People tab button) or Strategy 2 (profile page)
      _handle_connect_modal() → Variant A (note modal) or Variant B (direct send)
      log_connection() → append to connections.csv
  ↓
WebSocket sends {type:"done"} when finished
  ↓
app.js: loadAnalytics() + loadResults() refresh the UI
```

### 6.2 Messaging Flow

```
User clicks "Send Messages" in Msg Prospect tab
  ↓
app.js: startMsgRun() opens WebSocket to /ws/msg
  ↓
main.py: receives {action:"msg_run", msg_cap:int, scan_limit:int, speed_multiplier:float}
  ↓
messenger.run_messaging():
  1. Navigate to LinkedIn connections page
  2. _scrape_cards() — JS evaluate to get name/role/profileUrl/msgHref
  3. Filter out already-messaged (check messages.csv)
  4. For each new connection up to msg_cap:
      _send_message_to():
        - Navigate to compose URL directly (more reliable than clicking button)
        - Wait for .msg-form__contenteditable
        - Dismiss AI prompt if present
        - _generate_message() via Ollama/Gemini
        - Type into compose box
        - 5-second countdown (user can stop)
        - Click Send button
      log_message() → append to messages.csv
```

### 6.3 Follow-Up Flow

```
User clicks "Send Follow-Ups" in Follow Up tab
  ↓
app.js: startFollowupRun() opens WebSocket to /ws/followup
  ↓
main.py: receives {action:"followup_run", followup_cap:int, wait_days:int, speed_multiplier:float}
  ↓
messenger.run_followups():
  1. seed_followups_from_messages() — copy messages.csv → followups.csv (idempotent)
  2. Filter: status='pending' AND first_msg_sent_at <= cutoff (wait_days ago)
  3. For each candidate up to followup_cap:
      _check_replied():
        - Navigate to profile page
        - Click Message button (opens thread overlay)
        - Check last message CSS class (.msg-s-event-listitem--other vs --self)
        - Returns True if they replied
      If replied: upsert_followup(status='replied'), skip
      If not replied:
        - Compose overlay is already open (left open by _check_replied)
        - _generate_followup_message() via Ollama/Gemini
        - Type into compose box
        - 5-second countdown
        - Click Send
        - upsert_followup(status='followed_up')
```

### 6.4 WebSocket Control Protocol

All three automation WebSockets (connections, messaging, follow-ups) support mid-run control:

```json
// Sent from client to server during run:
{"action": "pause"}
{"action": "resume"}
{"action": "stop"}

// Sent from server to client:
{"type": "started"}
{"type": "log", "message": "..."}
{"type": "done"}
{"type": "error", "message": "..."}
```

### 6.5 AI Layer

`ai.py` supports two providers, switchable via `AI_PROVIDER` env var:

**Ollama (local, default):**
- Model: `llama3.1:8b` (configurable)
- Runs locally, no API costs
- Used for: title scoring, connection notes, first messages, follow-up messages
- Caveat: slower (~1-3 sec per call) — user has accepted this tradeoff

**Gemini (cloud):**
- Model: `gemini-2.0-flash-exp`
- Faster but requires API key and internet
- Same prompts/interface as Ollama

**Score caching:** `_title_score_cache` dict prevents re-scoring the same job title twice in a run. Cleared between runs via `clear_title_score_cache()`.

**Note template (connection requests):**
```
"Hi {first_name}, {ai_hook} Would love to connect."
```
AI fills only `{ai_hook}` — one role-specific sentence. Hard-trimmed to 280 chars (LinkedIn limit: 300).

---

## 7. DATA SCHEMAS

### connections.csv
```
sent_at | name | role | company | profile_url | score | scorer | note
```
- `score`: 0–10 integer from AI or keyword fallback
- `scorer`: "AI" or "keywords"
- `note`: the connection request note text (empty if sent without note)

### messages.csv
```
sent_at | name | role | profile_url | message
```

### followups.csv
```
profile_url | name | role | first_msg_sent_at | follow_up_sent_at | replied_at | status
```
- `status`: "pending" | "followed_up" | "replied"

### runs.jsonl
Each line is a JSON object:
```json
{
  "run_id": "20260221-143022",
  "started_at": "2026-02-21 14:30",
  "companies": ["Montai", "Stripe"],
  "entries": [{"ts": "14:30:01", "message": "...", "level": "info"}],
  "total_sent": 5,
  "finished_at": "2026-02-21 14:47"
}
```

### accepted_count.txt
Single integer, e.g. `15`. Written by the ↻ refresh button via `/ws/refresh-accepted`.

---

## 8. FRONTEND ARCHITECTURE

### 8.1 Layout

```
┌─────────────────────────────────────────────────────────────┐
│  header: "LinkedIn Automator"          [status badge: Idle] │
├─────────────────────────┬───────────────────────────────────┤
│  LEFT PANEL (420px)     │  RIGHT PANEL (flex 1)             │
│                         │                                   │
│  ┌─ Config ─────────┐   │  [Live Feed][Results][History]    │
│  │ Companies textarea│   │  [Msg Prospect][Follow Up]        │
│  │ Speed slider      │   │                                   │
│  │ Execute/Pause/Stop│   │  Tab content area                 │
│  │ Test AI           │   │                                   │
│  └──────────────────┘   │                                   │
│                         │                                   │
│  ┌─ Ring Widget ────┐   │                                   │
│  │ SVG: week/today  │   │                                   │
│  │ w/message rings  │   │                                   │
│  └──────────────────┘   │                                   │
│                         │                                   │
│  ┌─ THIS QUARTER ───┐   │                                   │
│  │ Req Sent: —      │   │                                   │
│  │ Accepted: —  [↻] │   │                                   │
│  │ Messages Sent: — │   │                                   │
│  │ Follow-ups: —    │   │                                   │
│  │ Connect→Msg: —%  │   │                                   │
│  └──────────────────┘   │                                   │
└─────────────────────────┴───────────────────────────────────┘
```

### 8.2 Right Panel Tabs

| Tab | ID | Content |
|-----|----|---------|
| Live Feed | `pane-feed` | Scrolling log of real-time automation messages |
| Results | `pane-results` | Table of connection requests sent (sortable by Score) |
| History | `pane-history` | Accordion list of past runs |
| Msg Prospect | `pane-msg` | Message cap slider, Send/Pause/Stop, message log table |
| Follow Up | `pane-followup` | Wait-days slider, cap slider, Send/Pause/Stop, follow-up table |

### 8.3 Speed Slider

4 positions (0–3):

| Value | Label | Behavior |
|-------|-------|---------|
| 0 | DEMO | ~0.1x speed — fast for testing |
| 1 | FAST | ~0.35x speed |
| 2 | NORMAL | ~0.6x speed |
| 3 | SAFE | 1.0x speed — 8-15s between requests |

`speed_multiplier` is passed to the WebSocket payload and threads through to every `asyncio.sleep()` call.

### 8.4 Score Sorting (Results Tab)

- Score column header `<th>` has class `th-sortable` and `onclick="sortByScore()"`
- Module-level `_scoreSort = null | 'desc' | 'asc'` in app.js
- `sortByScore()` cycles: null → desc → asc → desc...
- `renderResults(rows, total, animate=true)` sorts then animates rows:
  - Rows fade out (opacity 0, translateY -8px) in 60ms
  - Double `requestAnimationFrame` trick forces reflow
  - Rows stagger back in with 18ms offset per row
- Sort indicator `#sort-indicator` shows ▼ (desc) or ▲ (asc) or empty

### 8.5 Ring Widget (SVG)

Three concentric rings (SVG stroke-dasharray animation):
- **Outer (green):** This week's connections vs weekly cap (100)
- **Middle (blue):** Today's connections vs daily cap (30)
- **Inner (cyan):** Today's connections with message note vs daily message cap

`updateRings(week, today, notes, caps)` in app.js:
- Double `requestAnimationFrame` trick to force transition to trigger
- Staggered by 120ms per ring using `setTimeout`
- Cubic-bezier easing via CSS `transition`

### 8.6 Analytics / Quarterly Scorecard

`loadAnalytics()` → `GET /analytics` → `renderQuarterlyScorecard(data.quarterly)`

Displays: Requests Sent, Accepted, Messages Sent, Follow-ups Sent, Connect→Message Rate %

**Accepted count:** Persisted in `accepted_count.txt`. Baseline = 15 (set 2026-02-21). Updated by ↻ button which opens WebSocket to `/ws/refresh-accepted` → launches Playwright → navigates to LinkedIn connections page → scrolls → counts cards with "Connected on" date ≥ `ACCEPTED_BASELINE_DATE` → adds `ACCEPTED_BASELINE` (15) → writes total to `accepted_count.txt`.

**Quarter label** dynamically computed: "Q1 2026", "Q2 2026" etc.

**Auto-refresh:** `setInterval(loadAnalytics, 60_000)` — refreshes scorecard every 60 seconds.

### 8.7 Preflight Typewriter Animation

Each automation start (connections, messaging, follow-ups) triggers a short typewriter animation in the live feed before the WebSocket connects. Gives visual feedback that something is happening during the startup delay.

`typewriterLog(lines, callback)` — types each line character by character at ~40ms/char, then calls callback when done.

---

## 9. VISUAL DESIGN SYSTEM

**Aesthetic:** CRT terminal / green phosphor monitor. Dark, gritty, techy.

### Color Palette
```css
--bg:          #0a0a0a    /* near-black background */
--bg-panel:    #0d0d0d    /* panel background */
--bg-input:    #111111    /* input/textarea background */
--green:       #00ff41    /* primary green (Matrix green) */
--cyan:        #00d4ff    /* secondary accent */
--amber:       #ffb000    /* warning/accent */
--red:         #ff3333    /* danger/error */
--text-dim:    #4a5a4a    /* muted text */
--border:      #1a2a1a    /* subtle borders */
```

### CRT Effects
- `body::before` — scanline overlay (horizontal lines via repeating-linear-gradient, 2px tall, 15% opacity)
- `body::after` — phosphor vignette (radial-gradient, darkens edges)
- `@keyframes flicker` on `body` — subtle opacity flicker (99.5%→100%→99.2%) at 8s interval

### Panel Corners
Panels have CSS `::before`/`::after` pseudo-elements that draw corner bracket decorations (like `┌─` in terminal UI).

### Font
`Share Tech Mono` from Google Fonts. Applied globally. All text is monospace.

### Log Entry Colors
```
.log-success  → green glow text
.log-error    → red text
.log-warning  → amber text
.log-info     → dim green text
```

---

## 10. KEY IMPLEMENTATION DECISIONS & WHY

### Why Playwright over Selenium or puppeteer?
Playwright's `launch_persistent_context()` reuses a real Chrome profile — this is critical for LinkedIn. The user is already logged in under their real profile. No need to handle login at all.

### Why the `_is_in_aside()` check?
LinkedIn's profile pages show "People Also Viewed" sidebar with Connect buttons for OTHER people. Without this check, the automator was accidentally clicking Connect on random sidebar people instead of the profile being viewed. The `_is_in_aside()` function walks up the DOM to detect if a button is inside an `<aside>` or sidebar-class container.

### Why Strategy 1 (People tab) vs Strategy 2 (profile page)?
- Strategy 1 is faster (no page navigation) but LinkedIn sometimes shows a "Send now" modal without a note option from the People tab card.
- Strategy 2 (visiting the profile directly) gives the "Add a note" modal which allows attaching a personalized note.
- Both are attempted in sequence — Strategy 2 is always the fallback.

### Why `interop=msgOverlay` in compose URLs?
LinkedIn's messaging has two modes: the dedicated /messaging/ page, and the overlay that appears in the feed. The `interop=msgOverlay` parameter forces the overlay mode. More reliable than clicking the Message button because it works even when overlays are already open.

### Why navigate back to connections page between messages?
LinkedIn's messaging overlay state accumulates. If you open multiple overlays without returning to a clean page, compose boxes become unreliable. Returning to the connections page between each message gives a fresh DOM state.

### Why not use LinkedIn's official API?
LinkedIn's API is heavily restricted for personal developer use — connection requests are not allowed, messaging is gated behind partnership agreements. Playwright automation of the real UI is the only practical approach.

### Why CSVs instead of SQLite?
Simplicity. The user can open CSVs in Excel/Numbers to inspect data. No database setup required. For the scale of this tool (hundreds of rows, not millions), CSV performance is fine.

### Why flat files instead of a database for runs?
Same reason. JSONL (one JSON object per line) is simple, readable in a text editor, appendable without locking, and trivial to parse.

---

## 11. WHAT WAS BUILT (CHRONOLOGICAL FEATURE LOG)

### Phase 1: Core Connection Automation
- FastAPI app with single `/ws` WebSocket endpoint
- Playwright automation: company search → People tab → scrape cards → send connections
- Keyword-based title scoring (`_score_title()`)
- CSV logging to `connections.csv`
- Basic HTML frontend with textarea + Execute button
- Live log feed via WebSocket

### Phase 2: AI Integration
- `ai.py` module: Ollama + Gemini providers
- `score_title_ai()`: AI scores job titles 0–10 (with keyword fallback)
- `generate_connection_note()`: AI writes personalized connection request notes
- Template: "Hi {first_name}, {ai_hook} Would love to connect."
- `test_ai_connection()`: button in UI to verify AI is working

### Phase 3: Speed Slider
- 4-position range input: DEMO / FAST / NORMAL / SAFE
- `speed_multiplier` passed through WebSocket payload to automator
- All `asyncio.sleep()` calls scaled by multiplier
- CSS styled with custom tick marks and active label display

### Phase 4: Messaging Feature
- New `messenger.py` module
- `/ws/msg` WebSocket endpoint
- LinkedIn connections page scrape using JS evaluate
- Navigate directly to compose URL (more reliable)
- Dismiss LinkedIn Premium AI prompt
- 5-second countdown before send (safety feature)
- `messages.csv` logging
- "Msg Prospect" tab in right panel

### Phase 5: Follow-Up Feature
- `run_followups()` in messenger.py
- `followups.csv` with upsert-by-URL logic
- `seed_followups_from_messages()` — idempotent seeder from messages.csv
- Reply detection via `.msg-s-event-listitem--other` CSS class
- Wait-days slider (0–14 days configurable)
- "Follow Up" tab in right panel
- Follow-up log table

### Phase 6: Run History
- `run_logger.py` module
- JSONL format (`runs.jsonl`)
- "History" tab: accordion UI, expandable per-run log entries
- Color-coded log entries matching Live Feed colors
- Per-run stats: companies targeted, connections sent, start/end time

### Phase 7: Visual Polish & Ring Widget
- Triple-ring SVG progress widget
- Ring colors: outer (green), middle (blue), inner (cyan)
- Animated with `stroke-dashoffset` transitions
- Double-rAF trick for reliable CSS transition triggering
- CRT aesthetic: scanlines, vignette, flicker, phosphor glow
- Panel corner bracket decorations
- Status badge (Idle / Running / Paused / Done)

### Phase 8: Analytics — Quarterly Scorecard
- `logger.py`: `quarterly_connections_sent()`, `quarterly_messages_sent()`, `quarterly_followups_sent()`
- `/analytics` GET endpoint
- `renderQuarterlyScorecard()` in app.js
- Quarterly grid: Requests Sent, Accepted, Messages Sent, Follow-ups Sent, Connect→Msg %
- Quarter label auto-computed

### Phase 9: Accepted Count + Refresh Button
- `ACCEPTED_BASELINE = 15`, `ACCEPTED_BASELINE_DATE = "2026-02-21"` hardcoded in logger.py
- `accepted_count.txt` for persistence
- Subtle ↻ refresh button in quarterly scorecard header
- `/ws/refresh-accepted` WebSocket: opens Playwright, navigates LinkedIn connections page, counts new connections since baseline date, adds baseline (15), saves
- Button spins while refreshing (`@keyframes btn-spin`)

### Phase 10: Score Sorting on Results Tab
- Score column `<th>` made clickable (`th-sortable` class)
- `sortByScore()` function: cycles null→desc→asc
- `_scoreSort` module-level state variable
- `_buildRow()` extracted helper
- Animated sort: rows fade out then stagger back in with 18ms per-row offset
- Sort indicator ▼/▲ next to "Score" header

---

## 12. WHAT WAS TRIED AND DELETED

**This is the most important section for avoiding repeated mistakes.**

### Weekly Bar Chart — ATTEMPTED TWICE, DELETED TWICE

The user asked for a bar chart showing Mon–Sun activity (connections, messages, follow-ups) in the left config panel.

**Attempt 1 (vertical grouped bars):**
- 21 vertical bars (7 days × 3 metrics) side by side
- The left panel is 420px wide. With labels, the bars were ~12px wide each — too squished to read
- User said "visually this is out of place. the weekly bar chart is not properly lining up"
- Multiple fix attempts made — still unsatisfactory
- User said: **"delete the weekly dashboard"**
- Deleted

**Attempt 2 (horizontal sparkline rows):**
- 3 horizontal rows (one per metric), each row containing 7 cell-bars growing left-to-right
- Day labels at top, metric labels (Conn/Msg/F/U) at left
- Bars fill left-to-right proportionally
- Today's column highlighted with green outline
- HTML, JS (`renderWeeklyChart()`), and CSS (`.wk-*` classes) all implemented
- User said: **"delete your attempt at weekly bar chart."**
- Deleted again

**Current state:** Weekly chart does not exist anywhere in the codebase. The backend (`logger.py` and `/analytics` endpoint) still returns `weekly` data (7-int arrays), but `app.js`'s `loadAnalytics()` ignores it. Do not add a weekly chart unless the user explicitly asks again with a very specific design — and expect it to be deleted.

### Analytics as a Dedicated Tab
- At one point the weekly chart was moved to a 6th tab ("Analytics") in the right panel
- User: **"no do not create a dedicated analytics tab. i want the analytics to stay on the left side"**
- Reverted. Left panel is where analytics live. Right panel has only: Live Feed, Results, History, Msg Prospect, Follow Up.

### Quarterly Accepted Count via CSV Cross-Reference
- First approach: computed accepted count by cross-referencing connections.csv with messages.csv (people who got a message = accepted)
- Problem: missed connections accepted before the messaging feature existed, and missed connections that were accepted but not yet messaged
- Replaced with: hardcoded baseline (15) + Playwright scrape triggered by user

---

## 13. CURRENT KNOWN ISSUES / FRAGILE AREAS

### LinkedIn DOM Selectors (highest risk area)
LinkedIn frequently changes its class names and DOM structure. The most fragile selectors are:
- `li.org-people-profile-card__profile-card-spacing` (People tab cards)
- `div.org-people-profile-card__profile-info` (name/role extraction)
- `.msg-form__contenteditable` (compose box)
- `.msg-s-event-listitem--other` / `--self` (reply detection)
- `button[aria-label*='Invite'][aria-label*='connect']` (connect button)

If the automator starts failing to find people or send connections, these selectors are the first place to look. Use Chrome DevTools on a live LinkedIn page to verify the current class names.

### Chrome Profile Detection
```python
Path.home() / "Library" / "Application Support" / "Google" / "ChromeLinkedIn"
```
This is the preferred profile path. If it doesn't exist, falls back to the main Chrome profile. The dedicated "ChromeLinkedIn" profile keeps LinkedIn cookies isolated so other Chrome tabs don't interfere.

### CAPTCHA
The tool detects CAPTCHAs by checking for specific text patterns and URL keywords ("checkpoint", "challenge"). If a CAPTCHA appears, the tool logs an error and stops. The user must solve it manually in the browser, then restart the run.

LinkedIn is more likely to show CAPTCHAs if:
- Requests are too fast (use SAFE mode)
- Account is new to automation
- Too many requests in a day

### accepted_count.txt Scraping Reliability
The `/ws/refresh-accepted` WebSocket counts LinkedIn connection cards using:
```javascript
document.querySelectorAll('li.mn-connection-card, [data-view-name="connection-card"]')
```
And parses "Connected on ..." text. LinkedIn may change the card markup. If the count comes back as 0 when it should be higher, check these selectors in DevTools on the connections page.

### messenger_debug.log
`messenger.py` writes verbose debug output to `messenger_debug.log`. This file can grow large. It's in `.gitignore` (or should be). Safe to delete if it gets too big.

---

## 14. USER PREFERENCES & WORKING STYLE

**Critical for new Claude sessions to understand:**

- **Moves fast.** Does not want lengthy explanations before making changes. Prefers action.
- **Deletes things he doesn't like immediately.** If he says "delete X," delete it completely from all files (HTML, JS, CSS, Python). Do not leave stubs or comments.
- **Does not want to be asked many questions.** If something is ambiguous, make a reasonable judgment and proceed.
- **Prefers minimal, surgical edits.** Don't refactor things that are working. Don't "clean up" code that wasn't asked about.
- **The CRT/terminal aesthetic is intentional and non-negotiable.** Never suggest "modernizing" the UI or using a component library.
- **Analytics stay in the left panel.** The right panel has exactly 5 tabs (Live Feed, Results, History, Msg Prospect, Follow Up). No more tabs.
- **The weekly bar chart is a sore subject.** It was attempted twice and deleted twice. Do not attempt it again without explicit user direction and a very concrete design proposal.
- **He uses git commits and tags for milestones.** When he says "make this a milestone," create an annotated git tag.
- **He tests by running the actual automation.** The "Test AI" button is how he verifies AI is working. He does real LinkedIn runs.

---

## 15. API ENDPOINT REFERENCE

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serves index.html |
| GET | `/status` | Connection automation status |
| GET | `/msg-status` | Messaging automation status |
| GET | `/followup-status` | Follow-up automation status |
| GET | `/results` | All connections (newest first) |
| GET | `/messages` | All messages (newest first) |
| GET | `/followups` | All follow-up rows |
| GET | `/runs` | All run history (newest first) |
| GET | `/analytics` | Weekly (7-int arrays) + quarterly totals |
| GET | `/accepted-count` | Current accepted count (no browser) |
| GET | `/test-ai` | Test AI provider connectivity |
| POST | `/pause` | Pause connection automation |
| POST | `/resume` | Resume connection automation |
| POST | `/stop` | Stop connection automation |
| WS | `/ws` | Connection automation WebSocket |
| WS | `/ws/msg` | Messaging automation WebSocket |
| WS | `/ws/followup` | Follow-up automation WebSocket |
| WS | `/ws/refresh-accepted` | Scrape LinkedIn for accepted count |

---

## 16. CSS VARIABLE REFERENCE

```css
/* Core colors */
--bg: #0a0a0a
--bg-panel: #0d0d0d
--bg-input: #111111
--green: #00ff41
--cyan: #00d4ff
--amber: #ffb000
--red: #ff3333
--text-dim: #4a5a4a
--border: #1a2a1a

/* Glows */
--glow-green: 0 0 8px rgba(0, 255, 65, 0.4)
--glow-green-sm: 0 0 4px rgba(0, 255, 65, 0.3)
--glow-amber: 0 0 8px rgba(255, 176, 0, 0.4)
--glow-red: 0 0 8px rgba(255, 51, 51, 0.4)
--glow-cyan: 0 0 8px rgba(0, 212, 255, 0.4)
```

---

## 17. JAVASCRIPT FUNCTION REFERENCE (app.js)

### State Variables (module-level)
```javascript
let ws = null                 // connection automation WebSocket
let msgWs = null              // messaging WebSocket
let followupWs = null         // follow-up WebSocket
let _isRunning = false
let _isPaused = false
let _isMsgRunning = false
let _isMsgPaused = false
let _isFollowupRunning = false
let _isFollowupPaused = false
let _resultsRows = []         // cached results for re-sorting
let _scoreSort = null         // null | 'desc' | 'asc'
```

### Key Functions
```javascript
// Tab management
switchTab(tabName)             // switches visible tab pane

// Connection automation
startRun()                     // reads textarea, opens /ws WebSocket
togglePause()                  // sends pause/resume to WebSocket
stopRun()                      // sends stop to WebSocket

// Messaging
startMsgRun()                  // opens /ws/msg WebSocket
toggleMsgPause()
stopMsgRun()

// Follow-ups
startFollowupRun()             // opens /ws/followup WebSocket
toggleFollowupPause()
stopFollowupRun()

// Data loading
loadResults()                  // GET /results → renderResults()
loadMessages()                 // GET /messages → renders msg-table
loadFollowups()                // GET /followups → renders followup-table
loadHistory()                  // GET /runs → renders history accordion
loadAnalytics()                // GET /analytics → renderQuarterlyScorecard()
refreshAccepted()              // opens /ws/refresh-accepted WebSocket

// Rendering
renderResults(rows, total, animate=false)  // renders results table (handles sort)
_buildRow(row)                             // builds a <tr> for results table
sortByScore()                              // cycles sort state, re-renders
renderQuarterlyScorecard(q)               // fills quarterly grid
updateRings(week, today, notes, caps)     // animates SVG rings

// Preflight animations
typewriterLog(lines, callback)            // types lines into log at char-by-char speed
runPreflight(companies)                   // connection run typewriter sequence
msgPreflight(cap)                         // messaging run typewriter sequence
followupPreflight(cap, days)             // follow-up run typewriter sequence

// Logging
addLog(message, pane='feed')              // adds colored entry to a log pane
clearLog()                                // clears live feed pane

// Speed slider
updateSpeedLabel(value)                   // updates SAFE/NORMAL/FAST/DEMO label

// Slider bubbles
updateMsgCapBubble(input)                // shows current value for msg cap slider
updateFollowupCapBubble(input)           // shows current value for followup cap slider
updateFollowupDaysBubble(input)          // shows current value for days slider
```

---

## 18. PYTHON MODULE REFERENCE

### main.py
FastAPI app with all HTTP routes and WebSocket endpoints. Imports from all other modules. Manages global `asyncio.Task` instances for the three automation types.

### automator.py
Everything for connection request automation:
- `run_automation(company_list, log, speed_multiplier)` — main entry point
- `_find_company_page()` — fuzzy company search
- `_go_to_people_tab()` — navigate to /people/
- `_scrape_people_cards()` — DOM scrape + AI scoring
- `_send_connection()` — Strategy 1 (card button) + Strategy 2 (profile page)
- `_handle_connect_modal()` — Variant A (add note) + Variant B (direct send)
- `_find_profile_header_connect_btn()` — 4-tier button detection
- `_is_in_aside()` — sidebar detection to avoid wrong-person clicks
- `_detect_chrome_profile()` / `_detect_chrome_executable()` — auto-detection
- `request_stop()` / `request_pause()` / `request_resume()` / `reset_state()` — state control

### messenger.py
Messaging and follow-up automation:
- `run_messaging(msg_cap, scan_limit, log, speed_multiplier)` — main messaging entry
- `run_followups(followup_cap, wait_days, log, speed_multiplier)` — main follow-up entry
- `_scrape_cards()` — JS evaluate to get connection cards
- `_send_message_to()` — 7-step message send flow
- `_check_replied()` — reply detection via thread overlay
- `_click_message_button_on_profile()` — finds and clicks Message button
- `_generate_message()` / `_generate_followup_message()` — Ollama/Gemini prompts
- `_get_profile_urn()` / `_build_compose_url()` — URN-based compose URL construction
- Separate state control for messaging: `request_msg_stop()` etc.
- Separate state control for follow-ups: `request_followup_stop()` etc.
- `_flog` — file logger writing to `messenger_debug.log`

### ai.py
- `score_title_ai(role)` — AI scores 0–10, cached
- `generate_connection_note(first_name, company, role)` — note generation
- `generate_note(template, first_name, company, role)` — template-based generation
- `_generate_ollama()` / `_generate_gemini()` — provider implementations
- `test_ai_connection()` — health check
- `clear_title_score_cache()` — clears between runs

### logger.py
All data persistence:
- Connection: `log_connection()`, `read_connections()`, `count_sent_today()`, `count_sent_this_week()`, `count_notes_today()`
- Messages: `log_message()`, `read_messages()`, `count_messages_today()`
- Follow-ups: `upsert_followup()`, `read_followups()`, `seed_followups_from_messages()`, `count_followups_pending()`, `count_followups_today()`
- Analytics — weekly: `weekly_connections_by_day()`, `weekly_messages_by_day()`, `weekly_followups_by_day()` (all return 7-int arrays Mon=0…Sun=6)
- Analytics — quarterly: `quarterly_connections_sent()`, `quarterly_messages_sent()`, `quarterly_followups_sent()`, `quarterly_connections_accepted()`
- Accepted count: `set_accepted_count(count)`, `ACCEPTED_BASELINE=15`, `ACCEPTED_BASELINE_DATE="2026-02-21"`
- Schema migration: `_ensure_header()`, `_ensure_msg_header()`, `_ensure_followup_header()` — all three CSVs auto-migrate if column schema changes

### run_logger.py
- `start_run(companies)` → returns `run_id`
- `append_entry(run_id, message)` — adds to in-memory buffer
- `finish_run(run_id, total_sent)` — flushes to `runs.jsonl`
- `read_runs()` → list of run dicts, newest first
- `_detect_level(message)` — mirrors app.js level logic (error/warning/success/info)

---

## 19. FUTURE FEATURES (mentioned but not built)

These were discussed or implied but never implemented. Do not build these without explicit user request:

1. **Reply detection improvement** — Currently checks CSS class of last message bubble. Could be more robust by parsing message text.
2. **Connection request withdrawal** — Withdraw pending requests older than X days (LinkedIn recommends not letting requests sit too long).
3. **Multi-account support** — Currently assumes single Chrome profile.
4. **Export to CSV** — The data is already in CSVs, but a UI button to download them was never built.
5. **Email digest** — Weekly summary email of outreach stats.
6. **Scheduled runs** — Cron-like scheduling from within the UI.
7. **LinkedIn Sales Navigator support** — The tool currently uses free LinkedIn. Premium/SN has different DOM.
8. **Better analytics visualization** — The weekly bar chart was attempted twice and deleted twice. Any future attempt needs a completely different design approach.

---

## 20. QUICK DIAGNOSTIC CHECKLIST

If something isn't working, check in this order:

### App won't start
- [ ] `venv` activated? (`source venv/bin/activate`)
- [ ] In the right directory? (`cd /Users/jkw/LI/linkedin-automator`)
- [ ] `uvicorn main:app --reload --port 8000` throws an import error? → check requirements installed
- [ ] Port 8000 already in use? → `lsof -i :8000` to find and kill

### AI not working
- [ ] `AI_PROVIDER=ollama` → is Ollama running? (`ollama serve`)
- [ ] `ollama list` → is `llama3.1:8b` downloaded?
- [ ] `AI_PROVIDER=gemini` → is `GEMINI_API_KEY` set in `.env`?
- [ ] Click "Test AI" button → check browser log for error

### Connection automation not finding people
- [ ] LinkedIn DOM changed? → Inspect `li.org-people-profile-card__profile-card-spacing` in DevTools
- [ ] Company not found? → Fuzzy match threshold is 40 — try the exact LinkedIn company name
- [ ] Already at daily/weekly cap? → Check ring widget numbers

### Messaging not working
- [ ] Check `messenger_debug.log` for detailed step-by-step logs
- [ ] Compose box not found → LinkedIn changed `.msg-form__contenteditable`?
- [ ] "All connections already messaged" → messages.csv has their URL already

### Follow-ups not triggering
- [ ] `wait_days=0` to disable the time gate (test mode)
- [ ] `followups.csv` has the rows with status='pending'?
- [ ] Message button not found on profile? → LinkedIn changed profile layout

### Analytics showing wrong numbers
- [ ] `accepted_count.txt` exists? Contains `15`?
- [ ] Quarter boundary correct? → `_quarter_bounds()` in logger.py
- [ ] `/analytics` endpoint returning correct data? → Test directly in browser

---

## 21. CURRENT STATE SUMMARY (as of 2026-02-21)

**What's working:**
- Connection request automation (full pipeline: search → people tab → score → connect with note)
- Messaging automation (connections page scrape → AI message → send)
- Follow-up automation (reply detection → follow-up message)
- Run history accordion
- Quarterly scorecard with accepted count + ↻ refresh
- Score sorting on Results tab with animation
- Ring widget animation
- Speed slider (DEMO/FAST/NORMAL/SAFE)
- CRT visual aesthetic

**What's not built / was removed:**
- Weekly bar chart (deleted twice — backend data exists but UI is gone)

**Git tag:** `v1.0-milestone` at commit `2a81b2b`

**Branch:** `visual-updates` — clean (one unstaged change in index.html from the last weekly chart deletion, trivial)

**Data files:** Active, contain real outreach data. Do not delete.

**`accepted_count.txt`:** Contains `15` (the baseline set 2026-02-21).
