// State
let ws = null;
let isPaused = false;
let isRunning = false;
let activeTab = 'feed';

// DOM refs
const logEl = document.getElementById('log');
const statusBadge = document.getElementById('status-badge');
// cap counter replaced by dual-ring SVG widget — see updateRings()
const btnRun = document.getElementById('btn-run');
const btnPause = document.getElementById('btn-pause');
const btnStop = document.getElementById('btn-stop');

// ── Tabs ──────────────────────────────────────────────────────────────────────
function switchTab(tab) {
  activeTab = tab;

  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`tab-${tab}`).classList.add('active');

  document.querySelectorAll('.tab-pane').forEach(p => p.classList.add('hidden'));
  document.getElementById(`pane-${tab}`).classList.remove('hidden');

  document.getElementById('feed-clear-btn').classList.toggle('hidden', tab !== 'feed');
  document.getElementById('results-refresh-btn').classList.toggle('hidden', tab !== 'results');
  document.getElementById('history-refresh-btn').classList.toggle('hidden', tab !== 'history');

  if (tab === 'results') loadResults();
  if (tab === 'history') loadHistory();
}

// ── Results table ─────────────────────────────────────────────────────────────
async function loadResults() {
  try {
    const res = await fetch('/results');
    const data = await res.json();
    renderResults(data.rows, data.total);
  } catch (e) {
    console.error('Failed to load results:', e);
  }
}

function renderResults(rows, total) {
  const countEl = document.getElementById('results-count');
  const emptyEl = document.getElementById('results-empty');
  const tableEl = document.getElementById('results-table');
  const tbody   = document.getElementById('results-tbody');

  countEl.textContent = total > 0 ? total : '';

  if (!rows || rows.length === 0) {
    emptyEl.classList.remove('hidden');
    tableEl.classList.add('hidden');
    return;
  }

  emptyEl.classList.add('hidden');
  tableEl.classList.remove('hidden');
  tbody.innerHTML = '';

  rows.forEach(row => {
    const tr = document.createElement('tr');

    const scorerClass = row.scorer === 'AI' ? 'scorer-ai' : 'scorer-kw';
    const scoreHtml = `<span class="score-pill ${scorerClass}">${row.score} <span class="scorer-label">${row.scorer}</span></span>`;

    const nameHtml = row.profile_url
      ? `<a href="${escapeHtml(row.profile_url)}" target="_blank" rel="noopener">${escapeHtml(row.name)}</a>`
      : escapeHtml(row.name);

    const noteText = row.note || '';
    const noteHtml = noteText
      ? `<button class="col-note-text" onclick="this.classList.toggle('expanded')" title="Click to expand">${escapeHtml(noteText)}</button>`
      : `<span class="col-note-empty">—</span>`;

    tr.innerHTML = `
      <td class="col-date">${escapeHtml(row.sent_at)}</td>
      <td class="col-name">${nameHtml}</td>
      <td class="col-role">${escapeHtml(row.role)}</td>
      <td class="col-company">${escapeHtml(row.company)}</td>
      <td class="col-score">${scoreHtml}</td>
      <td class="col-note">${noteHtml}</td>
    `;
    tbody.appendChild(tr);
  });
}

// Auto-refresh results count badge when a run completes
function refreshResultsBadge() {
  fetch('/results')
    .then(r => r.json())
    .then(d => {
      const countEl = document.getElementById('results-count');
      countEl.textContent = d.total > 0 ? d.total : '';
      // If results tab is active, re-render
      if (activeTab === 'results') renderResults(d.rows, d.total);
    })
    .catch(() => {});
}

// ── History ───────────────────────────────────────────────────────────────────
async function loadHistory() {
  try {
    const res = await fetch('/runs');
    const data = await res.json();
    renderHistory(data.runs, data.total);
  } catch (e) {
    console.error('Failed to load history:', e);
  }
}

function renderHistory(runs, total) {
  const countEl  = document.getElementById('history-count');
  const emptyEl  = document.getElementById('history-empty');
  const listEl   = document.getElementById('history-list');

  countEl.textContent = total > 0 ? total : '';

  if (!runs || runs.length === 0) {
    emptyEl.classList.remove('hidden');
    listEl.innerHTML = '';
    return;
  }

  emptyEl.classList.add('hidden');
  listEl.innerHTML = '';

  runs.forEach(run => {
    // Build summary line
    const companies = (run.companies || []).join(', ') || '—';
    const sent      = run.total_sent != null ? run.total_sent : '?';
    const startedAt = run.started_at || run.run_id || '';
    const finishedAt = run.finished_at || null;

    // Duration
    let duration = '';
    if (startedAt && finishedAt) {
      const start = new Date(startedAt);
      const end   = new Date(finishedAt);
      const secs  = Math.round((end - start) / 1000);
      if (!isNaN(secs) && secs >= 0) {
        const m = Math.floor(secs / 60);
        const s = secs % 60;
        duration = m > 0 ? `${m}m ${s}s` : `${s}s`;
      }
    }

    const meta = [
      `${sent} sent`,
      duration,
    ].filter(Boolean).join(' · ');

    const item = document.createElement('div');
    item.className = 'run-item';

    const header = document.createElement('div');
    header.className = 'run-header';
    header.innerHTML = `
      <span class="run-chevron">›</span>
      <span class="run-date">${escapeHtml(startedAt)}</span>
      <span class="run-companies">${escapeHtml(companies)}</span>
      <span class="run-meta">${escapeHtml(meta)}</span>
    `;

    const body = document.createElement('div');
    body.className = 'run-body hidden';

    // Render log entries (same style as Live Feed)
    const entries = run.entries || [];
    if (entries.length === 0) {
      body.innerHTML = '<div class="run-no-entries">No log entries recorded.</div>';
    } else {
      entries.forEach(e => {
        const div = document.createElement('div');
        div.className = 'log-entry';
        div.innerHTML = `<span class="log-ts">${escapeHtml(e.ts || '')}</span><span class="log-msg ${escapeHtml(e.level || 'info')}">${escapeHtml(e.message || '')}</span>`;
        body.appendChild(div);
      });
    }

    // Toggle expand/collapse
    header.addEventListener('click', () => {
      const expanded = !body.classList.contains('hidden');
      body.classList.toggle('hidden', expanded);
      header.classList.toggle('expanded', !expanded);
    });

    item.appendChild(header);
    item.appendChild(body);
    listEl.appendChild(item);
  });
}

// Refresh history count badge when a run completes
function refreshHistoryBadge() {
  fetch('/runs')
    .then(r => r.json())
    .then(d => {
      const countEl = document.getElementById('history-count');
      countEl.textContent = d.total > 0 ? d.total : '';
      if (activeTab === 'history') renderHistory(d.runs, d.total);
    })
    .catch(() => {});
}

// ── Logging ───────────────────────────────────────────────────────────────────
function addLog(message, level = 'info') {
  const ts = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  if (level === 'info') {
    const lower = message.toLowerCase();
    if (lower.includes('error') || lower.includes('fatal') || lower.includes('captcha')) {
      level = 'error';
    } else if (lower.includes('warning') || lower.includes('skipping') || lower.includes('could not') || lower.includes('paused')) {
      level = 'warning';
    } else if (lower.includes('✓') || lower.includes('sent') || lower.includes('complete') || lower.includes('done')) {
      level = 'success';
    }
  }

  const entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.innerHTML = `<span class="log-ts">${ts}</span><span class="log-msg ${level}">${escapeHtml(message)}</span>`;
  logEl.appendChild(entry);
  logEl.scrollTop = logEl.scrollHeight;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function clearLog() {
  logEl.innerHTML = '';
}

// ── Status ────────────────────────────────────────────────────────────────────
function setStatus(state) {
  statusBadge.className = `badge ${state}`;
  const labels = { idle: 'Idle', running: 'Running', paused: 'Paused', done: 'Done', error: 'Error' };
  statusBadge.textContent = labels[state] || state;
}

async function refreshCapCounter() {
  try {
    const res  = await fetch('/status');
    const data = await res.json();
    updateRings(
      data.sent_today,    data.daily_cap,
      data.sent_this_week ?? 0, data.weekly_cap ?? 100,
      data.notes_today    ?? 0
    );
  } catch (e) { /* ignore */ }
}

function updateRings(sentToday, dailyCap, sentWeek, weeklyCap, notesToday) {
  const weekArc  = document.getElementById('ring-week');
  const connArc  = document.getElementById('ring-conn');
  const notesArc = document.getElementById('ring-notes');
  const weekNum  = document.getElementById('ring-label-week');
  const connNum  = document.getElementById('ring-label-conn');
  const widget   = document.querySelector('.ring-widget');

  if (!connArc) return;

  // Radii match the SVG (centre 100,100)
  const rWeek  = 88;
  const rConn  = 66;
  const rNotes = 44;
  const circWeek  = 2 * Math.PI * rWeek;
  const circConn  = 2 * Math.PI * rConn;
  const circNotes = 2 * Math.PI * rNotes;

  const weekPct  = weeklyCap > 0 ? Math.min(sentWeek   / weeklyCap, 1) : 0;
  const connPct  = dailyCap  > 0 ? Math.min(sentToday  / dailyCap,  1) : 0;
  const notesPct = dailyCap  > 0 ? Math.min(notesToday / dailyCap,  1) : 0;

  // ── Animate from empty → filled on every call ──────────────────────────────
  // Step 1: snap all arcs to "empty" (full offset = hidden) without transition
  const noTrans = 'stroke-dashoffset 0s';
  const arcs = [
    { el: weekArc,  circ: circWeek,  pct: weekPct  },
    { el: connArc,  circ: circConn,  pct: connPct  },
    { el: notesArc, circ: circNotes, pct: notesPct },
  ];

  arcs.forEach(({ el, circ }) => {
    if (!el) return;
    el.style.transition       = noTrans;
    el.style.strokeDasharray  = `${circ}`;
    el.style.strokeDashoffset = `${circ}`;   // fully hidden
  });

  // Step 2: on next frame, restore transitions with staggered delays and set target
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      arcs.forEach(({ el, circ, pct }, i) => {
        if (!el) return;
        el.style.transition       = `stroke-dashoffset 0.9s cubic-bezier(0.4,0,0.2,1) ${i * 120}ms`;
        el.style.strokeDashoffset = `${circ * (1 - pct)}`;
      });
    });
  });

  // ── Update labels ──────────────────────────────────────────────────────────
  if (weekNum) weekNum.textContent = `${sentWeek}/${weeklyCap}`;
  if (connNum) connNum.textContent = `${sentToday}/${dailyCap}`;

  // Update legend to show live message count
  const notesLegend = document.querySelector('.ring-legend-notes');
  if (notesLegend) notesLegend.textContent = `w/ Message (${notesToday})`;

  // Tooltip
  if (widget) widget.title =
    `Today: ${sentToday}/${dailyCap} · This week: ${sentWeek}/${weeklyCap} · w/ message: ${notesToday}`;
}

setInterval(() => { if (isRunning) refreshCapCounter(); }, 10000);
refreshCapCounter();
refreshResultsBadge();
refreshHistoryBadge();

// ── Button state ──────────────────────────────────────────────────────────────
function setRunning(running) {
  isRunning = running;
  btnRun.disabled = running;
  btnPause.disabled = !running;
  btnStop.disabled = !running;
}

// ── Run ───────────────────────────────────────────────────────────────────────
async function startRun() {
  const companiesRaw = document.getElementById('companies').value.trim();

  const companies = companiesRaw
    .split('\n')
    .map(c => c.trim())
    .filter(Boolean);

  if (companies.length === 0) {
    addLog('Please enter at least one company name.', 'error');
    return;
  }

  clearLog();
  switchTab('feed');
  setStatus('running');
  setRunning(true);
  isPaused = false;
  btnPause.textContent = 'Pause';

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    ws.send(JSON.stringify({
      action: 'run',
      companies: companies,
    }));
  };

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);

    if (msg.type === 'log') {
      addLog(msg.message);
    } else if (msg.type === 'started') {
      addLog('Automation started.', 'info');
    } else if (msg.type === 'done') {
      setStatus('done');
      setRunning(false);
      refreshCapCounter();
      refreshResultsBadge();
      refreshHistoryBadge();
      loadAnalytics();
      addLog('Session finished.', 'success');
      ws.close();
    } else if (msg.type === 'error') {
      addLog(`Error: ${msg.message}`, 'error');
      setStatus('error');
      setRunning(false);
      ws.close();
    }
  };

  ws.onerror = () => {
    addLog('WebSocket connection error.', 'error');
    setStatus('error');
    setRunning(false);
  };

  ws.onclose = () => {
    if (isRunning) {
      setStatus('idle');
      setRunning(false);
    }
  };
}

// ── Pause / Resume ────────────────────────────────────────────────────────────
function togglePause() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  if (isPaused) {
    ws.send(JSON.stringify({ action: 'resume' }));
    isPaused = false;
    btnPause.textContent = 'Pause';
    setStatus('running');
    addLog('Resumed.', 'info');
  } else {
    ws.send(JSON.stringify({ action: 'pause' }));
    isPaused = true;
    btnPause.textContent = 'Resume';
    setStatus('paused');
    addLog('Paused. Click Resume to continue.', 'warning');
  }
}

// ── Stop ──────────────────────────────────────────────────────────────────────
function stopRun() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ action: 'stop' }));
  addLog('Stop requested...', 'warning');
}

<<<<<<< Updated upstream
=======
// ── Messaging Run ─────────────────────────────────────────────────────────────
async function startMsgRun() {
  const msgFeed   = document.getElementById('msg-feed');
  const cap       = getMsgCap();
  const scanLimit = Math.max(cap * 3, 20);

  setMsgRunning(true);
  isMsgPaused = false;
  const pauseBtn = document.getElementById('btn-msg-pause');
  if (pauseBtn) pauseBtn.textContent = 'Pause';

  // Make sure the live feed inside the pane is visible
  msgFeed.innerHTML = '';

  await msgPreflight(cap, getSpeedPresetName());

  const speedMultiplier = getSpeedMultiplier();

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  msgWs = new WebSocket(`${proto}://${location.host}/ws/msg`);

  const addMsgLog = (message, level = 'info') => addLog(message, level, msgFeed);

  msgWs.onopen = () => {
    msgWs.send(JSON.stringify({
      action: 'msg_run',
      msg_cap: cap,
      scan_limit: scanLimit,
      speed_multiplier: speedMultiplier,
    }));
  };

  msgWs.onmessage = (event) => {
    const msg = JSON.parse(event.data);

    if (msg.type === 'log') {
      addMsgLog(msg.message);
    } else if (msg.type === 'started') {
      addMsgLog('Messaging run started.', 'info');
    } else if (msg.type === 'done') {
      setMsgRunning(false);
      refreshMsgBadge();
      refreshMsgStatus();
      loadAnalytics();
      addMsgLog('Messaging run finished.', 'success');
      msgWs.close();
    } else if (msg.type === 'error') {
      addMsgLog(`Error: ${msg.message}`, 'error');
      setMsgRunning(false);
      msgWs.close();
    }
  };

  msgWs.onerror = () => {
    addLog('WebSocket error — is the server running? Restart uvicorn and try again.', 'error', msgFeed);
    setMsgRunning(false);
  };

  msgWs.onclose = (evt) => {
    if (isMsgRunning) {
      addLog(`WebSocket closed unexpectedly (code ${evt.code}). Restart the server if needed.`, 'warning', msgFeed);
      setMsgRunning(false);
    }
  };
}

// ── Pause / Resume (messaging) ────────────────────────────────────────────────
function toggleMsgPause() {
  if (!msgWs || msgWs.readyState !== WebSocket.OPEN) return;
  const msgFeed = document.getElementById('msg-feed');

  if (isMsgPaused) {
    msgWs.send(JSON.stringify({ action: 'resume' }));
    isMsgPaused = false;
    const btn = document.getElementById('btn-msg-pause');
    if (btn) btn.textContent = 'Pause';
    addLog('Resumed.', 'info', msgFeed);
  } else {
    msgWs.send(JSON.stringify({ action: 'pause' }));
    isMsgPaused = true;
    const btn = document.getElementById('btn-msg-pause');
    if (btn) btn.textContent = 'Resume';
    addLog('Paused. Click Resume to continue.', 'warning', msgFeed);
  }
}

// ── Stop (messaging) ──────────────────────────────────────────────────────────
function stopMsgRun() {
  if (!msgWs || msgWs.readyState !== WebSocket.OPEN) return;
  const msgFeed = document.getElementById('msg-feed');
  msgWs.send(JSON.stringify({ action: 'stop' }));
  addLog('Stop requested...', 'warning', msgFeed);
}

>>>>>>> Stashed changes
// ── Test AI ───────────────────────────────────────────────────────────────────
async function testAI() {
  addLog('Testing AI connection...', 'info');
  try {
    const res = await fetch('/test-ai');
    const data = await res.json();
    if (data.success) {
      addLog(`AI OK [${data.provider}]: "${data.sample}"`, 'success');
    } else {
      addLog(`AI failed [${data.provider}]: ${data.error}`, 'error');
    }
  } catch (e) {
    addLog(`AI test request failed: ${e}`, 'error');
  }
}
<<<<<<< Updated upstream
=======

// ── Follow-up sliders ─────────────────────────────────────────────────────────
function updateFollowupDaysBubble(input) {
  const slider = input || document.getElementById('followup-days-slider');
  if (!slider) return;
  const bubble = document.getElementById('followup-days-bubble');
  if (!bubble) return;
  const val = parseInt(slider.value, 10);
  const min = parseInt(slider.min, 10);
  const max = parseInt(slider.max, 10);
  const pct = max > min ? (val - min) / (max - min) : 0;
  const wrap = slider.closest('.msg-cap-slider-wrap');
  if (wrap) wrap.style.setProperty('--val-pct', pct);
  bubble.textContent = val === 0 ? 'TEST' : val;
}

function updateFollowupCapBubble(input) {
  const slider = input || document.getElementById('followup-cap-slider');
  if (!slider) return;
  const bubble = document.getElementById('followup-cap-bubble');
  if (!bubble) return;
  const val = parseInt(slider.value, 10);
  const min = parseInt(slider.min, 10);
  const max = parseInt(slider.max, 10);
  const pct = (val - min) / (max - min);
  const wrap = slider.closest('.msg-cap-slider-wrap');
  if (wrap) wrap.style.setProperty('--val-pct', pct);
  bubble.textContent = val;
}

function getFollowupCap()  { return parseInt(document.getElementById('followup-cap-slider')?.value  ?? '5', 10); }
function getFollowupDays() { return parseInt(document.getElementById('followup-days-slider')?.value ?? '0', 10); }

// ── Follow-up button state ────────────────────────────────────────────────────
function setFollowupRunning(running) {
  isFollowupRunning = running;
  const btnRun   = document.getElementById('btn-followup-run');
  const btnPause = document.getElementById('btn-followup-pause');
  const btnStop  = document.getElementById('btn-followup-stop');
  if (btnRun)   btnRun.disabled   = running;
  if (btnPause) btnPause.disabled = !running;
  if (btnStop)  btnStop.disabled  = !running;
}

// ── Follow-up data ────────────────────────────────────────────────────────────
async function loadFollowups() {
  try {
    const res  = await fetch('/followups');
    const data = await res.json();
    renderFollowups(data.rows, data.total);
  } catch (e) {
    console.error('Failed to load followups:', e);
  }
}

const STATUS_PILL = {
  pending:      { cls: 'pill-pending',     label: 'Pending'      },
  replied:      { cls: 'pill-replied',     label: 'Replied ✓'    },
  followed_up:  { cls: 'pill-followed-up', label: 'Followed Up'  },
  done:         { cls: 'pill-done',        label: 'Done'         },
};

function renderFollowups(rows, total) {
  const countEl  = document.getElementById('followup-count');
  const emptyEl  = document.getElementById('followup-empty');
  const tableEl  = document.getElementById('followup-table');
  const tbody    = document.getElementById('followup-tbody');

  if (countEl) countEl.textContent = total > 0 ? total : '';

  if (!rows || rows.length === 0) {
    if (emptyEl) emptyEl.classList.remove('hidden');
    if (tableEl) tableEl.classList.add('hidden');
    return;
  }

  if (emptyEl) emptyEl.classList.add('hidden');
  if (tableEl) tableEl.classList.remove('hidden');
  tbody.innerHTML = '';

  rows.forEach(row => {
    const tr = document.createElement('tr');

    const nameHtml = row.profile_url
      ? `<a href="${escapeHtml(row.profile_url)}" target="_blank" rel="noopener">${escapeHtml(row.name)}</a>`
      : escapeHtml(row.name);

    const status  = row.status || 'pending';
    const pill    = STATUS_PILL[status] || { cls: 'pill-pending', label: status };
    const pillHtml = `<span class="status-pill ${pill.cls}">${pill.label}</span>`;

    const fuSent  = row.follow_up_sent_at || '—';

    tr.innerHTML = `
      <td class="col-date">${escapeHtml(row.first_msg_sent_at)}</td>
      <td class="col-name">${nameHtml}</td>
      <td class="col-role">${escapeHtml(row.role)}</td>
      <td class="col-status">${pillHtml}</td>
      <td class="col-date">${escapeHtml(fuSent)}</td>
    `;
    tbody.appendChild(tr);
  });
}

async function refreshFollowupStatus() {
  try {
    const res  = await fetch('/followup-status');
    const data = await res.json();
    const todayEl   = document.getElementById('followup-sent-today');
    const countEl   = document.getElementById('followup-count');
    if (todayEl) {
      const parts = [];
      if (data.followed_up_today > 0) parts.push(`${data.followed_up_today} sent today`);
      if (data.pending_count > 0)     parts.push(`${data.pending_count} pending`);
      todayEl.textContent = parts.join(' · ');
    }
  } catch (e) { /* ignore */ }
}

function refreshFollowupBadge() {
  fetch('/followups')
    .then(r => r.json())
    .then(d => {
      const countEl = document.getElementById('followup-count');
      if (countEl) countEl.textContent = d.total > 0 ? d.total : '';
      if (activeTab === 'followup') renderFollowups(d.rows, d.total);
    })
    .catch(() => {});
}

// ── Follow-up preflight typeout ───────────────────────────────────────────────
async function followupPreflight(cap, days, presetName) {
  const feed = document.getElementById('followup-feed');
  feed.innerHTML = '';
  await typewriterLog(`> INITIALISING FOLLOW-UP SEQUENCE...`, 'info', 22, feed);
  await new Promise(r => setTimeout(r, 180));
  await typewriterLog(`> FOLLOW-UP CAP: ${cap} | WAIT: ${days} DAY(S)`, 'info', 18, feed);
  await new Promise(r => setTimeout(r, 140));
  await typewriterLog(`> SPEED: ${presetName}`, 'info', 22, feed);
  await new Promise(r => setTimeout(r, 140));
  await typewriterLog(`> LAUNCHING CHROME — STAND BY...`, 'warning', 20, feed);
  await new Promise(r => setTimeout(r, 200));
}

// ── Follow-up Run ─────────────────────────────────────────────────────────────
async function startFollowupRun() {
  const feed = document.getElementById('followup-feed');
  const cap  = getFollowupCap();
  const days = getFollowupDays();

  setFollowupRunning(true);
  isFollowupPaused = false;
  const pauseBtn = document.getElementById('btn-followup-pause');
  if (pauseBtn) pauseBtn.textContent = 'Pause';

  await followupPreflight(cap, days, getSpeedPresetName());

  const speedMultiplier = getSpeedMultiplier();
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  followupWs = new WebSocket(`${proto}://${location.host}/ws/followup`);

  const addFollowupLog = (message, level = 'info') => addLog(message, level, feed);

  followupWs.onopen = () => {
    followupWs.send(JSON.stringify({
      action: 'followup_run',
      followup_cap: cap,
      wait_days: days,
      speed_multiplier: speedMultiplier,
    }));
  };

  followupWs.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === 'log') {
      addFollowupLog(msg.message);
    } else if (msg.type === 'started') {
      addFollowupLog('Follow-up run started.', 'info');
    } else if (msg.type === 'done') {
      setFollowupRunning(false);
      refreshFollowupBadge();
      refreshFollowupStatus();
      loadAnalytics();
      addFollowupLog('Follow-up run finished.', 'success');
      followupWs.close();
    } else if (msg.type === 'error') {
      addFollowupLog(`Error: ${msg.message}`, 'error');
      setFollowupRunning(false);
      followupWs.close();
    }
  };

  followupWs.onerror = () => {
    addFollowupLog('WebSocket error — is the server running? Restart uvicorn and try again.', 'error');
    setFollowupRunning(false);
  };

  followupWs.onclose = (evt) => {
    if (isFollowupRunning) {
      addFollowupLog(`WebSocket closed unexpectedly (code ${evt.code}).`, 'warning');
      setFollowupRunning(false);
    }
  };
}

// ── Pause / Resume (follow-up) ────────────────────────────────────────────────
function toggleFollowupPause() {
  if (!followupWs || followupWs.readyState !== WebSocket.OPEN) return;
  const feed = document.getElementById('followup-feed');
  if (isFollowupPaused) {
    followupWs.send(JSON.stringify({ action: 'resume' }));
    isFollowupPaused = false;
    const btn = document.getElementById('btn-followup-pause');
    if (btn) btn.textContent = 'Pause';
    addLog('Resumed.', 'info', feed);
  } else {
    followupWs.send(JSON.stringify({ action: 'pause' }));
    isFollowupPaused = true;
    const btn = document.getElementById('btn-followup-pause');
    if (btn) btn.textContent = 'Resume';
    addLog('Paused. Click Resume to continue.', 'warning', feed);
  }
}

// ── Stop (follow-up) ──────────────────────────────────────────────────────────
function stopFollowupRun() {
  if (!followupWs || followupWs.readyState !== WebSocket.OPEN) return;
  const feed = document.getElementById('followup-feed');
  followupWs.send(JSON.stringify({ action: 'stop' }));
  addLog('Stop requested...', 'warning', feed);
}

// ── Init follow-up sliders on load ────────────────────────────────────────────
refreshFollowupBadge();
setInterval(() => { if (isFollowupRunning) refreshFollowupStatus(); }, 10000);
window.addEventListener('load', () => {
  updateFollowupDaysBubble(null);
  updateFollowupCapBubble(null);
});

// ── Analytics: weekly bar chart + quarterly scorecard ─────────────────────────

async function loadAnalytics() {
  try {
    const res  = await fetch('/analytics');
    const data = await res.json();
    renderWeeklyChart(data.weekly);
    renderQuarterlyScorecard(data.quarterly);
  } catch (e) {
    console.error('Analytics fetch failed:', e);
  }
}

function renderWeeklyChart(weekly) {
  const container = document.getElementById('weekly-bar-chart');
  if (!container) return;

  const conn = weekly.connections;   // [7] Mon–Sun
  const msgs = weekly.messages;      // [7]
  const fups = weekly.followups;     // [7]

  // Scale bars to the tallest value (minimum 1 to avoid divide-by-zero)
  const maxVal = Math.max(1, ...conn, ...msgs, ...fups);

  container.innerHTML = '';

  // Highlight today's column (JS: 0=Sun → Mon-based index 0=Mon)
  const todayJs  = new Date().getDay();
  const todayIdx = todayJs === 0 ? 6 : todayJs - 1;

  for (let i = 0; i < 7; i++) {
    const group = document.createElement('div');
    group.className = 'bar-group' + (i === todayIdx ? ' bar-group-today' : '');

    [
      { val: conn[i], cls: 'bar-conn' },
      { val: msgs[i], cls: 'bar-msg'  },
      { val: fups[i], cls: 'bar-fu'   },
    ].forEach(({ val, cls }) => {
      const bar = document.createElement('div');
      bar.className = `bar ${cls}`;
      bar.style.height = `${Math.max((val / maxVal) * 100, val > 0 ? 6 : 0)}%`;
      bar.title = `${val}`;
      if (val > 0) {
        const lbl = document.createElement('span');
        lbl.className = 'bar-val';
        lbl.textContent = val;
        bar.appendChild(lbl);
      }
      group.appendChild(bar);
    });

    container.appendChild(group);
  }
}

function renderQuarterlyScorecard(q) {
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  set('q-conn-sent',     q.connections_sent);
  set('q-conn-accepted', q.connections_accepted);
  set('q-msg-sent',      q.messages_sent);
  set('q-fu-sent',       q.followups_sent);
  set('q-conv-pct',      `${q.conversion_pct}%`);

  // Label e.g. "Q1 2026"
  const now = new Date();
  const el  = document.getElementById('quarter-label');
  if (el) el.textContent = `Q${Math.floor(now.getMonth() / 3) + 1} ${now.getFullYear()}`;
}

// Load on startup; refresh every 60s and after each automation run completes
loadAnalytics();
setInterval(loadAnalytics, 60000);
>>>>>>> Stashed changes
