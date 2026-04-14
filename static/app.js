// State
let ws = null;
let isPaused = false;
let isRunning = false;
let activeTab = 'feed';

// DOM refs
const logEl       = document.getElementById('log');
const statusBadge = document.getElementById('status-badge');
const btnRun      = document.getElementById('btn-run');
const btnPause    = document.getElementById('btn-pause');
const btnStop     = document.getElementById('btn-stop');

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
let _resultsRows = [];
let _scoreSort   = null;

async function loadResults() {
  try {
    const res  = await fetch('/results');
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

  let sorted = [...rows];
  if (_scoreSort === 'desc') sorted.sort((a, b) => (Number(b.score) || 0) - (Number(a.score) || 0));
  if (_scoreSort === 'asc')  sorted.sort((a, b) => (Number(a.score) || 0) - (Number(b.score) || 0));

  if (animate && tbody.children.length > 0) {
    Array.from(tbody.children).forEach(tr => {
      tr.style.opacity   = '0';
      tr.style.transform = 'translateY(-6px)';
    });
    setTimeout(() => {
      tbody.innerHTML = '';
      sorted.forEach((row, i) => {
        const tr = _buildRow(row);
        tr.style.opacity   = '0';
        tr.style.transform = 'translateY(8px)';
        tbody.appendChild(tr);
        requestAnimationFrame(() => requestAnimationFrame(() => {
          tr.style.transitionDelay = `${i * 18}ms`;
          tr.style.opacity   = '1';
          tr.style.transform = 'translateY(0)';
        }));
      });
    }, 200);
  } else {
    tbody.innerHTML = '';
    sorted.forEach(row => tbody.appendChild(_buildRow(row)));
  }
}

function sortByScore() {
  _scoreSort = _scoreSort === 'desc' ? 'asc' : 'desc';
  const indicator = document.getElementById('sort-indicator');
  const th        = document.getElementById('th-score');
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
    const res  = await fetch('/runs');
    const data = await res.json();
    renderHistory(data.runs, data.total);
  } catch (e) {
    console.error('Failed to load history:', e);
  }
}

function renderHistory(runs, total) {
  const countEl = document.getElementById('history-count');
  const emptyEl = document.getElementById('history-empty');
  const listEl  = document.getElementById('history-list');

  countEl.textContent = total > 0 ? total : '';

  if (!runs || runs.length === 0) {
    emptyEl.classList.remove('hidden');
    listEl.innerHTML = '';
    return;
  }

  emptyEl.classList.add('hidden');
  listEl.innerHTML = '';

  runs.forEach(run => {
    const titleLabel = run.title_query || (run.companies || []).join(', ') || '—';
    const sent       = run.total_sent != null ? run.total_sent : '?';
    const startedAt  = run.started_at || run.run_id || '';
    const finishedAt = run.finished_at || null;

    let duration = '';
    if (startedAt && finishedAt) {
      const secs = Math.round((new Date(finishedAt) - new Date(startedAt)) / 1000);
      if (!isNaN(secs) && secs >= 0) {
        const m = Math.floor(secs / 60), s = secs % 60;
        duration = m > 0 ? `${m}m ${s}s` : `${s}s`;
      }
    }

    const meta = [`${sent} sent`, duration].filter(Boolean).join(' · ');

    const item   = document.createElement('div');
    item.className = 'run-item';

    const header = document.createElement('div');
    header.className = 'run-header';
    header.innerHTML = `
      <span class="run-chevron">›</span>
      <span class="run-date">${escapeHtml(startedAt)}</span>
      <span class="run-companies">${escapeHtml(titleLabel)}</span>
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

function clearLog() { logEl.innerHTML = ''; }

// ── Speed slider ──────────────────────────────────────────────────────────────
const SPEED_PRESETS = [
  { key: 'demo',   label: 'DEMO MODE',   cls: 'demo',   hint: '~1s between requests  ⚠ HIGH RISK',  multiplier: 0.1  },
  { key: 'fast',   label: 'FAST MODE',   cls: 'fast',   hint: '~3–5s between requests',              multiplier: 0.35 },
  { key: 'normal', label: 'NORMAL MODE', cls: 'normal', hint: '~5–8s between requests',              multiplier: 0.6  },
  { key: 'safe',   label: 'SAFE MODE',   cls: 'safe',   hint: '8–15s between requests',              multiplier: 1.0  },
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
      data.sent_today,         data.daily_cap,
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
  const weekPct  = weeklyCap > 0 ? Math.min(sentWeek  / weeklyCap, 1) : 0;
  const connPct  = dailyCap  > 0 ? Math.min(sentToday / dailyCap,  1) : 0;
  const notesPct = dailyCap  > 0 ? Math.min(notesToday / dailyCap, 1) : 0;

  const arcs = [
    { el: weekArc,  circ: circWeek,  pct: weekPct  },
    { el: connArc,  circ: circConn,  pct: connPct  },
    { el: notesArc, circ: circNotes, pct: notesPct },
  ];

  arcs.forEach(({ el, circ }) => {
    if (!el) return;
    el.style.transition       = 'stroke-dashoffset 0s';
    el.style.strokeDasharray  = `${circ}`;
    el.style.strokeDashoffset = `${circ}`;
  });

  requestAnimationFrame(() => requestAnimationFrame(() => {
    arcs.forEach(({ el, circ, pct }, i) => {
      if (!el) return;
      el.style.transition       = `stroke-dashoffset 0.9s cubic-bezier(0.4,0,0.2,1) ${i * 120}ms`;
      el.style.strokeDashoffset = `${circ * (1 - pct)}`;
    });
  }));

  if (weekNum) weekNum.textContent = `${sentWeek}/${weeklyCap}`;
  if (connNum) connNum.textContent = `${sentToday}/${dailyCap}`;
  if (widget)  widget.title = `Today: ${sentToday}/${dailyCap} · This week: ${sentWeek}/${weeklyCap}`;
}

setInterval(() => { if (isRunning) refreshCapCounter(); }, 10000);
refreshCapCounter();
refreshResultsBadge();
refreshHistoryBadge();

// ── Button state ──────────────────────────────────────────────────────────────
function setRunning(running) {
  isRunning = running;
  btnRun.disabled   = running;
  btnPause.disabled = !running;
  btnStop.disabled  = !running;
}

// ── Pre-flight typeout ────────────────────────────────────────────────────────
async function typewriterLog(message, level = 'info', charDelay = 28) {
  const ts    = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  const tsSpan  = document.createElement('span');
  tsSpan.className = 'log-ts';
  tsSpan.textContent = ts;
  const msgSpan = document.createElement('span');
  msgSpan.className = `log-msg ${level}`;
  entry.appendChild(tsSpan);
  entry.appendChild(msgSpan);
  logEl.appendChild(entry);
  logEl.scrollTop = logEl.scrollHeight;

  for (const ch of message) {
    msgSpan.textContent += ch;
    logEl.scrollTop = logEl.scrollHeight;
    await new Promise(r => setTimeout(r, charDelay + Math.random() * 20));
  }
}

async function runPreflight(titleQuery, presetName) {
  await typewriterLog(`> INITIALISING SEQUENCE...`, 'info', 22);
  await new Promise(r => setTimeout(r, 180));
  await typewriterLog(`> SEARCHING: ${titleQuery}`, 'info', 18);
  await new Promise(r => setTimeout(r, 140));
  await typewriterLog(`> SPEED: ${presetName}`, 'info', 22);
  await new Promise(r => setTimeout(r, 140));
  await typewriterLog(`> LAUNCHING CHROME — STAND BY...`, 'warning', 20);
  await new Promise(r => setTimeout(r, 200));
}

// ── Connection Run ────────────────────────────────────────────────────────────
async function startRun() {
  const titleQuery = document.getElementById('jobTitle').value.trim();

  if (!titleQuery) {
    addLog('Please enter a job title to search.', 'error');
    return;
  }

  clearLog();
  switchTab('feed');
  setStatus('running');
  setRunning(true);
  isPaused = false;
  btnPause.textContent = 'Pause';

  await runPreflight(titleQuery, getSpeedPresetName());

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    ws.send(JSON.stringify({
      action: 'run',
      title: titleQuery,
      speed_multiplier: getSpeedMultiplier(),
      profile: 1,
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
    if (isRunning) { setStatus('idle'); setRunning(false); }
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

// ── Test AI ───────────────────────────────────────────────────────────────────
async function testAI() {
  addLog('Testing AI connection...', 'info');
  try {
    const res  = await fetch('/test-ai');
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
  set('q-conv-pct',      `${q.conversion_pct}%`);
  const el = document.getElementById('quarter-label');
  const now = new Date();
  if (el) el.textContent = `Q${Math.floor(now.getMonth() / 3) + 1} ${now.getFullYear()}`;
}

loadAnalytics();
setInterval(loadAnalytics, 60000);
