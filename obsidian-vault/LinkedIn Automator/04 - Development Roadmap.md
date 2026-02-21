---
tags: [linkedin-automator, roadmap]
created: 2026-02-21
---

# 🗺️ Development Roadmap

← [[00 - Home]]

---

## ✅ Completed

### Phase 1 — Foundation
- [x] Playwright persistent Chrome context (reuses real session)
- [x] LinkedIn company search + profile scraping
- [x] AI scoring (keyword + Ollama/Gemini)
- [x] Connection request automation with personalized note
- [x] Daily/weekly cap enforcement
- [x] FastAPI backend with WebSocket log streaming
- [x] Real-time dashboard UI

### Phase 2 — First Message
- [x] Msg Prospect tab with messages-per-run slider
- [x] Connection card scraping via JS DOM evaluation
- [x] `[data-view-name="message-button"]` selector (confirmed from Web Inspector)
- [x] Direct compose URL navigation (more reliable than clicking button)
- [x] Ollama message generation (warm, non-salesy prompt)
- [x] Deduplication against `messages.csv`
- [x] 5-second send countdown with abort
- [x] LinkedIn Premium AI prompt dismissal

### Phase 3 — Follow-Up Sequence
- [x] `followups.csv` schema + CRUD (`upsert_followup`, `seed_followups_from_messages`)
- [x] Follow Up tab with days slider + cap slider
- [x] Reply detection via message bubble CSS classes
- [x] Profile page Message `<button>` click (not `<a>` tag)
- [x] Compose overlay opens on profile page (no page jump)
- [x] AI follow-up generation referencing original message
- [x] Status tracking: `pending` → `followed_up` / `replied`
- [x] AI quote stripping (`.strip('"').strip("'")`)

### Phase 4 — Hardening
- [x] Git history cleanup (PII purged via `filter-branch`)
- [x] `.gitignore` pattern-based (`*.csv`, `*.log`, `*.jsonl`)
- [x] `messages.csv` recovery from git stash
- [x] README updated (no Sales Navigator references)
- [x] `messenger_debug.log` file-based verbose logging

---

## 🔲 Planned — Near Term

### Smart Follow-Up Timing
- [ ] Respect `wait_days` per-person (already built, just set slider > 0)
- [ ] Skip weekends when calculating wait (B2B best practice)
- [ ] Configurable follow-up window (e.g. only send Mon–Thu 9am–5pm)

### Reply Handling
- [ ] When `replied` detected: log reply timestamp to `followups.csv`
- [ ] UI: show "Replied ✓" rows in green in the Follow-Up table
- [ ] Optional: notify user (desktop notification or email) when someone replies

### Message Quality
- [ ] A/B testing: rotate between 2 message templates, track which gets more replies
- [ ] Message preview before send (show in UI, require click to confirm)
- [ ] Per-company custom message context (e.g. "mention their recent Series B")
- [ ] Tone selector: Professional / Casual / Direct

---

## 🔲 Planned — Medium Term

### Analytics
- [ ] Reply rate tracking (replied / followed_up)
- [ ] Connection acceptance rate
- [ ] Best-performing message templates
- [ ] Time-of-day send analysis
- [ ] Simple dashboard charts (Chart.js)

### Campaign Management
- [ ] Named campaigns (group companies + message templates together)
- [ ] Campaign start/stop/archive
- [ ] Per-campaign stats (sent, replied, converted)

### Multi-Step Sequences
- [ ] Step 2 follow-up (after follow-up also gets no reply)
- [ ] Sequence designer: define N steps with N-day gaps
- [ ] Hard stop: never contact someone more than 3 times total

---

## 🔲 Planned — Longer Term

### Profile Intelligence
- [ ] Pull profile headline, recent posts, mutual connections before messaging
- [ ] Feed profile context into AI prompt for hyper-personalization
- [ ] Detect job changes: "Congratulations on the new role at..."

### Safety & Rate Limiting
- [ ] Randomized send times (not all at :00 or :30)
- [ ] Auto-pause if LinkedIn shows any warning banners
- [ ] Monthly cap tracking (LinkedIn restricts ~100 connection requests/week)
- [ ] Exponential backoff on repeated CAPTCHA

### Export & Integrations
- [ ] Export `followups.csv` to Notion database
- [ ] Export to Google Sheets (via gspread)
- [ ] Webhook on reply detected (Zapier / Make compatible)
- [ ] Slack notification on reply

---

## 💡 Ideas Backlog

| Idea | Notes |
|------|-------|
| LinkedIn Sales Navigator support | Removed from scope (no SN access) |
| Profile photo scraping | Privacy risk — not planned |
| Auto-accept connection requests | Passive mode — could add |
| Message thread summarization | Read thread → AI summary in UI |
| "Warm" detection | If they liked/commented your post, use warmer opener |
| Connection quality score | Based on title/company/mutual connections |
