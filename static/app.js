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

  if (weekArc) {
    weekArc.style.strokeDasharray  = `${circWeek}`;
    weekArc.style.strokeDashoffset = `${circWeek * (1 - weekPct)}`;
  }
  connArc.style.strokeDasharray  = `${circConn}`;
  connArc.style.strokeDashoffset = `${circConn * (1 - connPct)}`;
  notesArc.style.strokeDasharray  = `${circNotes}`;
  notesArc.style.strokeDashoffset = `${circNotes * (1 - notesPct)}`;

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
