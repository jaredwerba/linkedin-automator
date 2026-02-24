// State
let ws = null;
let msgWs = null;
let followupWs = null;
let creepWs = null;
let isPaused = false;
let isMsgPaused = false;
let isFollowupPaused = false;
let isCreepPaused = false;
let isRunning = false;
let isMsgRunning = false;
let isFollowupRunning = false;
let isCreepRunning = false;
let activeTab = 'feed';

// Active outreach profile (persisted in localStorage)
let _activeProfile = parseInt(localStorage.getItem('activeProfile') || '1', 10);

const _profileNames = {
  1: 'CLOUD INFRA · GENERAL',
  2: 'CLOUD INFRA · OCI SAVINGS',
  3: 'VENTURE CAPITAL',
};

// DOM refs
const logEl = document.getElementById('log');
const statusBadge = document.getElementById('status-badge');
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
  document.getElementById('msg-refresh-btn').classList.toggle('hidden', tab !== 'msg');
  document.getElementById('followup-refresh-btn').classList.toggle('hidden', tab !== 'followup');
  document.getElementById('creep-refresh-btn').classList.toggle('hidden', tab !== 'creep');

  if (tab === 'results') loadResults();
  if (tab === 'history') loadHistory();
  if (tab === 'msg') { loadMessages(); refreshMsgStatus(); updateMsgCapBubble(null); }
  if (tab === 'followup') {
    loadFollowups();
    refreshFollowupStatus();
    updateFollowupDaysBubble(null);
    updateFollowupCapBubble(null);
  }
  if (tab === 'creep') { loadCreepLog(); updateCreepCapBubble(null); initCreepFeed(); }
}

// ── Results table ─────────────────────────────────────────────────────────────
let _resultsRows = [];          // cached rows for re-sort without re-fetch
let _scoreSort   = null;        // null | 'desc' | 'asc'

async function loadResults() {
  try {
    const res = await fetch('/results');
    const data = await res.json();
    _resultsRows = data.rows || [];
    renderResults(_resultsRows, data.total);
  } catch (e) {
    console.error('Failed to load results:', e);
  }
}

function _buildRow(row) {
  const tr = document.createElement('tr');
  tr.style.transition = 'opacity 0.25s ease, transform 0.25s ease';

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
  return tr;
}

function renderResults(rows, total, animate = false) {
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

  // Apply current sort order
  let sorted = [...rows];
  if (_scoreSort === 'desc') sorted.sort((a, b) => (Number(b.score) || 0) - (Number(a.score) || 0));
  if (_scoreSort === 'asc')  sorted.sort((a, b) => (Number(a.score) || 0) - (Number(b.score) || 0));

  if (animate && tbody.children.length > 0) {
    // Fade + slide existing rows out
    Array.from(tbody.children).forEach(tr => {
      tr.style.opacity   = '0';
      tr.style.transform = 'translateY(-6px)';
    });
    setTimeout(() => {
      tbody.innerHTML = '';
      sorted.forEach((row, i) => {
        const tr = _buildRow(row);
        // Start invisible, stagger in
        tr.style.opacity   = '0';
        tr.style.transform = 'translateY(8px)';
        tbody.appendChild(tr);
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            tr.style.transitionDelay = `${i * 18}ms`;
            tr.style.opacity   = '1';
            tr.style.transform = 'translateY(0)';
          });
        });
      });
    }, 200);
  } else {
    tbody.innerHTML = '';
    sorted.forEach(row => tbody.appendChild(_buildRow(row)));
  }
}

function sortByScore() {
  // Cycle: none → desc → asc → desc …
  _scoreSort = _scoreSort === 'desc' ? 'asc' : 'desc';

  // Update header indicator
  const indicator = document.getElementById('sort-indicator');
  const th = document.getElementById('th-score');
  if (indicator) indicator.textContent = _scoreSort === 'desc' ? ' ▼' : ' ▲';
  if (th) th.classList.add('th-sorted');

  renderResults(_resultsRows, _resultsRows.length, true);
}

function refreshResultsBadge() {
  fetch('/results')
    .then(r => r.json())
    .then(d => {
      _resultsRows = d.rows || [];
      const countEl = document.getElementById('results-count');
      countEl.textContent = d.total > 0 ? d.total : '';
      if (activeTab === 'results') renderResults(_resultsRows, d.total);
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
    const companies = (run.companies || []).join(', ') || '—';
    const sent      = run.total_sent != null ? run.total_sent : '?';
    const startedAt = run.started_at || run.run_id || '';
    const finishedAt = run.finished_at || null;

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

    const meta = [`${sent} sent`, duration].filter(Boolean).join(' · ');

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

// ── Messages (Msg Prospect tab) ───────────────────────────────────────────────
async function loadMessages() {
  try {
    const res = await fetch('/messages');
    const data = await res.json();
    renderMessages(data.rows, data.total);
  } catch (e) {
    console.error('Failed to load messages:', e);
  }
}

function renderMessages(rows, total) {
  const countEl  = document.getElementById('msg-count');
  const emptyEl  = document.getElementById('msg-empty');
  const tableEl  = document.getElementById('msg-table');
  const tbody    = document.getElementById('msg-tbody');

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

    const nameHtml = row.profile_url
      ? `<a href="${escapeHtml(row.profile_url)}" target="_blank" rel="noopener">${escapeHtml(row.name)}</a>`
      : escapeHtml(row.name);

    const msgText = row.message || '';
    const msgHtml = msgText
      ? `<button class="col-note-text" onclick="this.classList.toggle('expanded')" title="Click to expand">${escapeHtml(msgText)}</button>`
      : `<span class="col-note-empty">—</span>`;

    tr.innerHTML = `
      <td class="col-date">${escapeHtml(row.sent_at)}</td>
      <td class="col-name">${nameHtml}</td>
      <td class="col-role">${escapeHtml(row.role)}</td>
      <td class="col-note">${msgHtml}</td>
    `;
    tbody.appendChild(tr);
  });
}

async function refreshMsgStatus() {
  try {
    const res  = await fetch('/msg-status');
    const data = await res.json();
    const todayEl = document.getElementById('msg-sent-today');
    if (todayEl) {
      todayEl.textContent = data.messages_today > 0
        ? `${data.messages_today} sent today`
        : '';
    }
  } catch (e) { /* ignore */ }
}

function refreshMsgBadge() {
  fetch('/messages')
    .then(r => r.json())
    .then(d => {
      const countEl = document.getElementById('msg-count');
      countEl.textContent = d.total > 0 ? d.total : '';
      if (activeTab === 'msg') renderMessages(d.rows, d.total);
    })
    .catch(() => {});
}

// ── Logging ───────────────────────────────────────────────────────────────────
function addLog(message, level = 'info', targetEl = null) {
  const el = targetEl || logEl;
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
  el.appendChild(entry);
  el.scrollTop = el.scrollHeight;
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

// ── Speed slider ──────────────────────────────────────────────────────────────
const SPEED_PRESETS = [
  { key: 'demo',   label: 'DEMO MODE',   cls: 'demo',   hint: '~1s between requests  ⚠ HIGH RISK',   multiplier: 0.1  },
  { key: 'fast',   label: 'FAST MODE',   cls: 'fast',   hint: '~3–5s between requests',               multiplier: 0.35 },
  { key: 'normal', label: 'NORMAL MODE', cls: 'normal', hint: '~5–8s between requests',               multiplier: 0.6  },
  { key: 'safe',   label: 'SAFE MODE',   cls: 'safe',   hint: '8–15s between requests',               multiplier: 1.0  },
];

function updateSpeedLabel(val) {
  const preset = SPEED_PRESETS[parseInt(val, 10)];
  const el = document.getElementById('speed-label');
  if (!el || !preset) return;
  el.className = `speed-label ${preset.cls}`;
  el.textContent = `${preset.label} — ${preset.hint}`;
}

function getSpeedMultiplier() {
  const val = document.getElementById('speed-slider')?.value ?? '3';
  return SPEED_PRESETS[parseInt(val, 10)]?.multiplier ?? 1.0;
}

function getSpeedPresetName() {
  const val = document.getElementById('speed-slider')?.value ?? '3';
  return SPEED_PRESETS[parseInt(val, 10)]?.label ?? 'SAFE MODE';
}

// ── Message cap slider ────────────────────────────────────────────────────────
function updateMsgCapBubble(input) {
  const slider = input || document.getElementById('msg-cap-slider');
  if (!slider) return;
  const bubble = document.getElementById('msg-cap-bubble');
  if (!bubble) return;
  const val = parseInt(slider.value, 10);
  const min = parseInt(slider.min, 10);   // 1
  const max = parseInt(slider.max, 10);   // 10
  // pct: 0 at min, 1 at max
  const pct = (val - min) / (max - min);
  // Set --val-pct on the WRAPPER so the bubble (sibling of slider) can inherit it
  const wrap = slider.closest('.msg-cap-slider-wrap');
  if (wrap) wrap.style.setProperty('--val-pct', pct);
  bubble.textContent = val;
}

function getMsgCap() {
  return parseInt(document.getElementById('msg-cap-slider')?.value ?? '5', 10);
}

// Init on load AND whenever the msg tab is shown
window.addEventListener('load', () => updateMsgCapBubble(null));

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

  const rWeek=88, rConn=66, rNotes=44;
  const circWeek=2*Math.PI*rWeek, circConn=2*Math.PI*rConn, circNotes=2*Math.PI*rNotes;
  const weekPct  = weeklyCap > 0 ? Math.min(sentWeek   / weeklyCap, 1) : 0;
  const connPct  = dailyCap  > 0 ? Math.min(sentToday  / dailyCap,  1) : 0;
  const notesPct = dailyCap  > 0 ? Math.min(notesToday / dailyCap,  1) : 0;

  const arcs = [
    { el: weekArc,  circ: circWeek,  pct: weekPct  },
    { el: connArc,  circ: circConn,  pct: connPct  },
    { el: notesArc, circ: circNotes, pct: notesPct },
  ];
  // Step 1: snap all arcs to empty (no transition)
  arcs.forEach(({ el, circ }) => {
    if (!el) return;
    el.style.transition       = 'stroke-dashoffset 0s';
    el.style.strokeDasharray  = `${circ}`;
    el.style.strokeDashoffset = `${circ}`;
  });
  // Step 2: double-rAF so browser commits the empty state first, then animates
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      arcs.forEach(({ el, circ, pct }, i) => {
        if (!el) return;
        el.style.transition       = `stroke-dashoffset 0.9s cubic-bezier(0.4,0,0.2,1) ${i * 120}ms`;
        el.style.strokeDashoffset = `${circ * (1 - pct)}`;
      });
    });
  });

  if (weekNum) weekNum.textContent = `${sentWeek}/${weeklyCap}`;
  if (connNum) connNum.textContent = `${sentToday}/${dailyCap}`;

  const notesLegend = document.querySelector('.ring-legend-notes');
  if (notesLegend) notesLegend.textContent = `w/ Message (${notesToday})`;

  if (widget) widget.title =
    `Today: ${sentToday}/${dailyCap} · This week: ${sentWeek}/${weeklyCap} · w/ message: ${notesToday}`;
}

setInterval(() => { if (isRunning) refreshCapCounter(); }, 10000);
refreshCapCounter();
refreshResultsBadge();
refreshHistoryBadge();
refreshMsgBadge();

// ── Button state ──────────────────────────────────────────────────────────────
function setRunning(running) {
  isRunning = running;
  btnRun.disabled = running;
  btnPause.disabled = !running;
  btnStop.disabled = !running;
}

function setMsgRunning(running) {
  isMsgRunning = running;
  const btnMsgRun   = document.getElementById('btn-msg-run');
  const btnMsgPause = document.getElementById('btn-msg-pause');
  const btnMsgStop  = document.getElementById('btn-msg-stop');
  if (btnMsgRun)   btnMsgRun.disabled   = running;
  if (btnMsgPause) btnMsgPause.disabled = !running;
  if (btnMsgStop)  btnMsgStop.disabled  = !running;
}

// ── Pre-flight typeout ────────────────────────────────────────────────────────
async function typewriterLog(message, level = 'info', charDelay = 28, targetEl = null) {
  const el = targetEl || logEl;
  const ts = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  const tsSpan  = document.createElement('span');
  tsSpan.className = 'log-ts';
  tsSpan.textContent = ts;
  const msgSpan = document.createElement('span');
  msgSpan.className = `log-msg ${level}`;
  entry.appendChild(tsSpan);
  entry.appendChild(msgSpan);
  el.appendChild(entry);
  el.scrollTop = el.scrollHeight;

  for (const ch of message) {
    msgSpan.textContent += ch;
    el.scrollTop = el.scrollHeight;
    await new Promise(r => setTimeout(r, charDelay + Math.random() * 20));
  }
}

async function runPreflight(companies, presetName) {
  const companyList = companies.join(', ');
  await typewriterLog(`> INITIALISING SEQUENCE...`, 'info', 22);
  await new Promise(r => setTimeout(r, 180));
  await typewriterLog(`> TARGETS: ${companyList}`, 'info', 18);
  await new Promise(r => setTimeout(r, 140));
  await typewriterLog(`> SPEED: ${presetName}`, 'info', 22);
  await new Promise(r => setTimeout(r, 140));
  await typewriterLog(`> LAUNCHING CHROME — STAND BY...`, 'warning', 20);
  await new Promise(r => setTimeout(r, 200));
}

async function msgPreflight(cap, presetName) {
  const msgFeed = document.getElementById('msg-feed');
  msgFeed.innerHTML = '';
  await typewriterLog(`> INITIALISING MESSAGING SEQUENCE...`, 'info', 22, msgFeed);
  await new Promise(r => setTimeout(r, 180));
  await typewriterLog(`> MESSAGE CAP: ${cap}`, 'info', 18, msgFeed);
  await new Promise(r => setTimeout(r, 140));
  await typewriterLog(`> SPEED: ${presetName}`, 'info', 22, msgFeed);
  await new Promise(r => setTimeout(r, 140));
  await typewriterLog(`> LAUNCHING CHROME — STAND BY...`, 'warning', 20, msgFeed);
  await new Promise(r => setTimeout(r, 200));
}

// ── Connection Run ─────────────────────────────────────────────────────────────
async function startRun() {
  // Pixelate out the duck when automation begins
  const duck = document.getElementById('duck-bg');
  if (duck) duck.classList.add('pixelate-out');

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

  await runPreflight(companies, getSpeedPresetName());

  const speedMultiplier = getSpeedMultiplier();

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    ws.send(JSON.stringify({
      action: 'run',
      companies: companies,
      speed_multiplier: speedMultiplier,
      profile: _activeProfile,
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

// ── Pause / Resume (connections) ──────────────────────────────────────────────
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

// ── Stop (connections) ────────────────────────────────────────────────────────
function stopRun() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ action: 'stop' }));
  addLog('Stop requested...', 'warning');
}

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

// ── Load target companies ──────────────────────────────────────────────────────
async function loadTargets() {
  try {
    const res  = await fetch('/targets');
    const data = await res.json();
    const companies = data.companies || [];
    if (!companies.length) {
      addLog('No targets found in targets.csv.', 'warning');
      return;
    }
    const ta = document.getElementById('companies');
    ta.style.transition = 'opacity 0.3s ease';
    ta.style.opacity = '0';
    setTimeout(() => {
      ta.value = companies.join('\n');
      ta.style.opacity = '1';
      addLog(`Loaded ${companies.length} target companies.`, 'success');
    }, 300);
  } catch (e) {
    addLog('Failed to load targets.', 'error');
  }
}

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

// ── Analytics ─────────────────────────────────────────────────────────────────

async function loadAnalytics() {
  try {
    const res  = await fetch('/analytics');
    const data = await res.json();
    renderQuarterlyScorecard(data.quarterly);
  } catch (e) { console.error('Analytics fetch failed:', e); }
}

function renderQuarterlyScorecard(q) {
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  set('q-conn-sent',     q.connections_sent);
  set('q-conn-accepted', q.connections_accepted);
  set('q-msg-sent',      q.messages_sent);
  set('q-fu-sent',       q.followups_sent);
  set('q-conv-pct',      `${q.conversion_pct}%`);
  const now = new Date();
  const el  = document.getElementById('quarter-label');
  if (el) el.textContent = `Q${Math.floor(now.getMonth() / 3) + 1} ${now.getFullYear()}`;
}

loadAnalytics();
setInterval(loadAnalytics, 60000);

// ── Accepted-connections refresh ───────────────────────────────────────────────
function refreshAccepted() {
  const btn = document.getElementById('btn-refresh-accepted');
  if (!btn || btn.disabled) return;
  btn.classList.add('spinning');
  btn.disabled = true;

  const ws = new WebSocket(`ws://${location.host}/ws/refresh-accepted`);

  ws.onmessage = ({ data }) => {
    try {
      const msg = JSON.parse(data);
      if (msg.type === 'done') {
        const el = document.getElementById('q-conn-accepted');
        if (el) el.textContent = msg.accepted;
        btn.classList.remove('spinning');
        btn.disabled = false;
        ws.close();
      } else if (msg.type === 'error') {
        console.error('refresh-accepted error:', msg.message);
        btn.classList.remove('spinning');
        btn.disabled = false;
        ws.close();
      }
    } catch (e) { /* ignore parse errors */ }
  };

  ws.onerror = () => {
    btn.classList.remove('spinning');
    btn.disabled = false;
  };
}


// ── Creep Mode ────────────────────────────────────────────────────────────────

async function initCreepFeed() {
  // Only show init sequence if not currently running
  if (isCreepRunning) return;
  const feed = document.getElementById('creep-feed');
  if (!feed) return;
  feed.innerHTML = '';

  const cap = getCreepCap();

  // Fetch connections to preview which profiles will be visited
  try {
    const res  = await fetch('/results');
    const data = await res.json();
    const rows = (data.rows || []).filter(r => r.profile_url && r.profile_url.trim());

    const total = rows.length;
    const queued = Math.min(cap, total);

    // Header banner
    const banner = document.createElement('div');
    banner.className = 'log-entry info';
    banner.textContent = `▸ CREEP MODE — ${queued} profile(s) queued from ${total} connection(s)`;
    feed.appendChild(banner);

    if (!total) {
      const empty = document.createElement('div');
      empty.className = 'log-entry warning';
      empty.textContent = '  No connections with profile URLs found. Run a connection search first.';
      feed.appendChild(empty);
      return;
    }

    // List the profiles that will be visited
    const preview = document.createElement('div');
    preview.className = 'log-entry info';
    preview.textContent = '  Sequence:';
    feed.appendChild(preview);

    rows.slice(0, queued).forEach((r, i) => {
      const name    = r.name || 'Unknown';
      const company = r.company ? ` @ ${r.company}` : '';
      const line = document.createElement('div');
      line.className = 'log-entry';
      line.textContent = `  ${i + 1}. ${name}${company}`;
      feed.appendChild(line);
    });

    if (total > queued) {
      const more = document.createElement('div');
      more.className = 'log-entry info';
      more.textContent = `  … and ${total - queued} more (adjust slider to include)`;
      feed.appendChild(more);
    }

  } catch (e) {
    const err = document.createElement('div');
    err.className = 'log-entry warning';
    err.textContent = '  Could not load connection preview.';
    feed.appendChild(err);
  }
}

function updateCreepCapBubble(input) {
  const slider = input || document.getElementById('creep-cap-slider');
  const bubble = document.getElementById('creep-cap-bubble');
  if (!slider || !bubble) return;
  bubble.textContent = slider.value;
  const pct = (slider.value - slider.min) / (slider.max - slider.min);
  bubble.style.left = `calc(${pct * 100}% + ${8 - pct * 16}px)`;
}

function getCreepCap() {
  return parseInt(document.getElementById('creep-cap-slider').value, 10) || 5;
}

function setCreepRunning(running) {
  isCreepRunning = running;
  document.getElementById('btn-creep-run').disabled   = running;
  document.getElementById('btn-creep-pause').disabled = !running;
  document.getElementById('btn-creep-stop').disabled  = !running;
  if (!running) {
    isCreepPaused = false;
    document.getElementById('btn-creep-pause').textContent = 'Pause';
  }
}

function addCreepLog(message, level) {
  const feed = document.getElementById('creep-feed');
  if (!feed) return;
  const div = document.createElement('div');
  div.className = `log-entry ${level || ''}`;
  div.textContent = message;
  feed.appendChild(div);
  feed.scrollTop = feed.scrollHeight;
}

function startCreepRun() {
  if (isCreepRunning) return;
  const feed = document.getElementById('creep-feed');
  if (feed) feed.innerHTML = '';

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  creepWs = new WebSocket(`${proto}://${location.host}/ws/creep`);

  creepWs.onopen = () => {
    creepWs.send(JSON.stringify({
      action: 'creep_run',
      profile_cap: getCreepCap(),
      speed_multiplier: 1.0,
    }));
  };

  creepWs.onmessage = (evt) => {
    const data = JSON.parse(evt.data);
    if (data.type === 'started') {
      setCreepRunning(true);
    } else if (data.type === 'log') {
      const lvl = data.message.startsWith('✓') ? 'success'
                : data.message.startsWith('✗') || data.message.includes('Error') ? 'error'
                : data.message.startsWith('⚠') ? 'warning'
                : 'info';
      addCreepLog(data.message, lvl);
    } else if (data.type === 'done' || data.type === 'error') {
      setCreepRunning(false);
      loadCreepLog();
      if (data.type === 'error') addCreepLog('Error: ' + (data.message || ''), 'error');
    }
  };

  creepWs.onerror = () => {
    addCreepLog('WebSocket error — is the server running?', 'error');
    setCreepRunning(false);
  };

  creepWs.onclose = () => {
    setCreepRunning(false);
  };
}

function toggleCreepPause() {
  if (!creepWs || !isCreepRunning) return;
  if (!isCreepPaused) {
    creepWs.send(JSON.stringify({ action: 'creep_pause' }));
    isCreepPaused = true;
    document.getElementById('btn-creep-pause').textContent = 'Resume';
  } else {
    creepWs.send(JSON.stringify({ action: 'creep_resume' }));
    isCreepPaused = false;
    document.getElementById('btn-creep-pause').textContent = 'Pause';
  }
}

function stopCreepRun() {
  if (!creepWs || !isCreepRunning) return;
  creepWs.send(JSON.stringify({ action: 'creep_stop' }));
}

async function loadCreepLog() {
  try {
    const res  = await fetch('/creep-log');
    const data = await res.json();
    renderCreepTable(data.rows || []);
  } catch (e) {
    console.error('loadCreepLog failed', e);
  }
}

function renderCreepTable(rows) {
  const tbody   = document.getElementById('creep-tbody');
  const table   = document.getElementById('creep-table');
  const empty   = document.getElementById('creep-empty');
  if (!tbody || !table || !empty) return;

  if (!rows.length) {
    table.classList.add('hidden');
    empty.classList.remove('hidden');
    return;
  }

  table.classList.remove('hidden');
  empty.classList.add('hidden');
  tbody.innerHTML = rows.map(r => {
    const liked = r.post_liked === 'yes'
      ? '<span class="creep-liked-yes">✓</span>'
      : '<span class="creep-liked-no">—</span>';
    const name = r.name || '—';
    const url  = r.profile_url
      ? `<a href="${r.profile_url}" target="_blank" rel="noopener">${name}</a>`
      : name;
    return `<tr>
      <td>${r.creeped_at || ''}</td>
      <td>${name}</td>
      <td>${url}</td>
      <td>${liked}</td>
    </tr>`;
  }).join('');
}


// ── Obsidian status dot ───────────────────────────────────────────────────────

async function checkObsidianStatus() {
  const dot = document.getElementById('obsidian-dot');
  if (!dot) return;
  dot.className = 'obsidian-dot checking';
  dot.title = 'Obsidian: checking...';
  try {
    const res  = await fetch('/obsidian-status');
    const data = await res.json();
    if (data.connected) {
      dot.className = 'obsidian-dot connected';
      dot.title = 'Obsidian: connected';
    } else if (data.configured) {
      dot.className = 'obsidian-dot disconnected';
      dot.title = 'Obsidian: configured but not running — open Obsidian with the Local REST API plugin enabled';
    } else {
      dot.className = 'obsidian-dot disconnected';
      dot.title = 'Obsidian: not configured (set OBSIDIAN_API_KEY in .env)';
    }
  } catch {
    dot.className = 'obsidian-dot disconnected';
    dot.title = 'Obsidian: unreachable';
  }
}

// Check on load, then every 30s
checkObsidianStatus();
setInterval(checkObsidianStatus, 30000);

// ── Outreach Profile Config ────────────────────────────────────────────────────

function openConfig() {
  _refreshProfileCards();
  const overlay = document.getElementById('config-overlay');
  overlay.classList.remove('closing');
  overlay.classList.remove('hidden');
}

function closeConfig() {
  const overlay = document.getElementById('config-overlay');
  if (overlay.classList.contains('hidden')) return;
  overlay.classList.add('closing');
  overlay.addEventListener('animationend', () => {
    overlay.classList.add('hidden');
    overlay.classList.remove('closing');
  }, { once: true });
}

function onOverlayClick(e) {
  if (e.target === document.getElementById('config-overlay')) {
    closeConfig();
  }
}

function selectProfile(id) {
  _activeProfile = id;
  localStorage.setItem('activeProfile', String(id));

  // Flash the selected card, then close after the flash completes
  const card = document.getElementById(`profile-card-${id}`);
  if (card) {
    card.classList.add('selecting');
    card.addEventListener('animationend', () => {
      card.classList.remove('selecting');
      _refreshProfileCards();
      _updateProfileLabel();
      closeConfig();
    }, { once: true });
  } else {
    _refreshProfileCards();
    _updateProfileLabel();
    closeConfig();
  }
}

function _refreshProfileCards() {
  [1, 2, 3].forEach(id => {
    const card = document.getElementById(`profile-card-${id}`);
    if (!card) return;
    if (id === _activeProfile) {
      card.classList.add('active');
    } else {
      card.classList.remove('active');
    }
  });
}

function _updateProfileLabel() {
  const label = document.getElementById('active-profile-label');
  if (!label) return;
  label.textContent = _profileNames[_activeProfile] || `PROFILE ${_activeProfile}`;
  // Restart animation to sweep in the new text
  label.classList.remove('updating');
  void label.offsetWidth; // force reflow
  label.classList.add('updating');
  label.addEventListener('animationend', () => label.classList.remove('updating'), { once: true });
}

// Init profile UI on page load
_updateProfileLabel();
_refreshProfileCards();
