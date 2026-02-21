---
tags: [linkedin-automator, debugging, logs]
created: 2026-02-21
---

# 🐛 Debugging & Logs

← [[00 - Home]]

---

## Log Files

| File | What's in it | How to read |
|------|-------------|-------------|
| `messenger_debug.log` | Step-by-step automation trace | `tail -50 messenger_debug.log` |
| Live Feed tab | WebSocket stream during run | Visible in UI |
| Follow Up tab live feed | Follow-up specific stream | Visible in UI |

---

## messenger_debug.log Structure

Each run starts with a header:
```
============================================================
FOLLOWUP RUN START  2026-02-21T13:57:07  cap=5 wait_days=0 speed=1.0
============================================================
```

Then per-person entries:
```
Processing Tomer Fuss Sanderovich | url=https://linkedin.com/in/tomer-...
  Reply check: navigating to https://linkedin.com/in/tomer-...
  Clicking Message button on profile page...
  Found Message button via: main button:has-text('Message')
  Clicked Message button — waiting for compose overlay...
  Compose overlay appeared (selector: .msg-form__contenteditable)
  Reply check: last_sender=unknown
  Compose box found via .msg-form__contenteditable
  AI follow-up full: Hi Tomer, I hope you're doing well!...
  Clicked Send button
  Follow-up sent and logged for Tomer Fuss Sanderovich
```

---

## Common Issues & Fixes

### Chrome doesn't open
**Symptom:** Button clicked, nothing happens, no log output.
**Fix:** Restart uvicorn. Old process may still be running.
```bash
# Kill the old process
lsof -ti:8000 | xargs kill -9
# Restart
uvicorn main:app --reload --port 8000
```

### "No messageable connections found"
**Symptom:** Run starts, Chrome opens connections page, exits immediately.
**Fix:** The scan didn't find `[data-view-name="message-button"]` elements. Try scrolling LinkedIn first, or increase scan_limit.

### "All connections already messaged"
**Symptom:** Run starts, skips everyone, exits.
**Fix:** Expected behavior — everyone in view has been messaged. Either wait for new connections or increase scan_limit.

### Follow-up: "Nothing to follow up on yet"
**Symptom:** Follow-up run exits before Chrome opens.
**Fix:** Either:
- Set days slider to 0 (test mode — messages all pending immediately)
- Or wait the required number of days since first messages

### "Compose box not found"
**Symptom:** Chrome opens the right page but nothing is typed.
**Fix:** LinkedIn may have changed their DOM. Check `messenger_debug.log` for which selector failed. Share the Web Inspector HTML of the compose area.

### CAPTCHA detected
**Symptom:** Run pauses, log shows "CAPTCHA detected".
**Fix:** Solve the CAPTCHA manually in the Chrome window, then restart the run.

### AI generates message with quotes
**Symptom:** Message starts with `"Hi...` or `'Hi...`.
**Status:** Fixed — both `_generate_message` and `_generate_followup_message` strip leading/trailing quotes with `.strip('"').strip("'")`.

### "Keyboard.type: Target page has been closed"
**Symptom:** Exception in log, Chrome window closes mid-run.
**Cause:** User closed Chrome manually, or Chrome crashed.
**Fix:** Let the automation finish before interacting with the Chrome window. Use Stop button to cancel cleanly.

---

## Selector Reference

Selectors confirmed working as of 2026-02-21:

| Element | Selector | Location |
|---------|---------|----------|
| Message button (connections list) | `[data-view-name="message-button"]` | `/mynetwork/invite-connect/connections/` |
| Message link on card | `a[aria-label="Message"]` | Inside message-button wrapper |
| Message button (profile page) | `main button:has-text('Message')` | Profile page hero section |
| Compose text box | `.msg-form__contenteditable` | Messaging overlay |
| Compose text box (fallback) | `div[role='textbox']` | Messaging overlay |
| Send button | `button.msg-form__send-button` | Messaging overlay |
| Send button (fallback) | `button[aria-label='Send']` | Messaging overlay |
| Last msg (them) | `.msg-s-event-listitem--other` | Thread overlay |
| Last msg (us) | `.msg-s-event-listitem--self` | Thread overlay |

> [!tip] When selectors break
> LinkedIn occasionally updates their DOM. When something stops working, right-click the element in Chrome → Inspect → share the HTML with Claude to get the updated selector.

---

## Key Bugs Fixed (Session History)

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| All 10 cards showed same person | JS walk-up overshot shared parent | Reduced from 5 to 3 levels + `seenHrefs` Set |
| Compose box "outside viewport" | Stale element handle after Ollama | Re-query compose box after AI call |
| 2nd+ messages never sent | Overlay state broke after first | Navigate directly to compose URL |
| Follow-up skipped everyone | `<a>` selector on profile page | Profile page uses `<button>` — click it directly |
| Follow-up jumped to messaging tab | navigating compose URL | Stay on profile, click Message button, overlay opens there |
| AI message wrapped in quotes | Ollama wraps output in `"..."` | Strip with `.strip('"').strip("'")` |
| Chrome never opened in follow-up | `wait_days` min was 1, blocked same-day messages | Lowered min to 0 |
