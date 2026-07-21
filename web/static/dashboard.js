let ALL_JOBS = [];
let currentStatus = 'new';
let agentSocket = null;

let _renderedCount = 0;
const BATCH_SIZE = 25;
let _lazyJobs = [];
let _lazyObserver = null;

let _selectMode = false;
let _selected = new Set();

let _badgeFilters = new Set();

let _availableSources = [];
let _sourcesMap = {};

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function safeUrl(u) {
  return (typeof u === 'string' && u.startsWith('http')) ? u : '#';
}

function scoreClass(s) {
  if (s == null) return 'score-none';
  if (s >= 7) return 'score-high';
  if (s >= 5) return 'score-mid';
  return 'score-low';
}

function formatDate(d) {
  if (!d) return '';
  return new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2500);
}

async function loadStats() {
  let r, s;
  try {
    r = await fetch('/api/stats');
    s = await r.json();
  } catch {
    return;
  }
  document.getElementById('s-total').textContent         = s.total;
  document.getElementById('s-new').textContent           = s.new;
  document.getElementById('s-reviewed').textContent      = s.reviewed;
  document.getElementById('s-applied').textContent       = s.applied;
  document.getElementById('s-rejected').textContent      = s.rejected;
  document.getElementById('s-auto-rejected').textContent = s.auto_rejected;
  document.getElementById('s-avg').textContent           = s.avg_score || '—';
  const lastRun = s.last_run ? new Date(s.last_run.replace(' ', 'T') + 'Z').toLocaleString('pl-PL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : 'never';
  document.getElementById('last-updated').textContent    = 'Last run: ' + lastRun;
  document.getElementById('btn-reevaluate').style.display = s.auto_rejected > 0 ? '' : 'none';
  document.getElementById('btn-rescore').style.display    = s.new > 0 ? '' : 'none';
  const btnRank = document.getElementById('btn-rank');
  if (btnRank) btnRank.style.display = s.new > 0 ? '' : 'none';
  const elRanked = document.getElementById('s-ranked');
  if (elRanked) elRanked.textContent = s.ranked ?? '—';
  const u = s.usage || {};
  const elToday = document.getElementById('s-cost-today');
  const elTotal = document.getElementById('s-cost-total');
  if (elToday) elToday.textContent = u.today_cost_usd != null ? `$${u.today_cost_usd.toFixed(3)}` : '—';
  if (elTotal) elTotal.textContent = u.total_cost_usd != null ? `$${u.total_cost_usd.toFixed(2)} total` : '';
  const noCvBanner = document.getElementById('no-cv-banner');
  if (noCvBanner) noCvBanner.style.display = (!s.has_cv && s.total > 0) ? '' : 'none';
  checkMissingDescriptions();
}

async function checkMissingDescriptions() {
  const r = await fetch('/api/jobs/missing-descriptions');
  const d = await r.json();
  const btn = document.getElementById('btn-backfill');
  if (d.count > 0) {
    document.getElementById('backfill-count').textContent = d.count;
    btn.style.display = '';
  } else {
    btn.style.display = 'none';
  }
}

function reevaluateRejected() {
  const log  = document.getElementById('activity-log');
  const badge = document.getElementById('activity-status-badge');
  log.textContent = '';
  badge.textContent = 'Running';
  badge.className = 'activity-status-badge running';
  document.getElementById('activity-modal').style.display = 'flex';
  document.getElementById('btn-activity-stop').style.display = 'none';

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/reevaluate-rejected`);

  let _done = false;

  ws.onmessage = e => {
    if (e.data.includes('__DONE__')) {
      _done = true;
      ws.close();
      badge.textContent = 'Done';
      badge.className = 'activity-status-badge done';
      loadStats();
      loadJobs();
      return;
    }
    log.textContent += e.data;
    log.scrollTop = log.scrollHeight;
  };

  ws.onerror = () => {
    if (_done) return;
    log.textContent += '\nWebSocket error.\n';
    badge.textContent = 'Error';
    badge.className = 'activity-status-badge done';
  };
}

function rescoreNew() {
  const log   = document.getElementById('activity-log');
  const badge = document.getElementById('activity-status-badge');
  log.textContent = '';
  badge.textContent = 'Running';
  badge.className = 'activity-status-badge running';
  document.getElementById('activity-modal').style.display = 'flex';
  document.getElementById('btn-activity-stop').style.display = 'none';

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/rescore-new`);
  let _done = false;

  ws.onmessage = e => {
    if (e.data.includes('__DONE__')) {
      _done = true;
      ws.close();
      badge.textContent = 'Done';
      badge.className = 'activity-status-badge done';
      loadStats();
      loadJobs();
      return;
    }
    log.textContent += e.data;
    log.scrollTop = log.scrollHeight;
  };

  ws.onerror = () => {
    if (_done) return;
    log.textContent += '\nWebSocket error.\n';
    badge.textContent = 'Error';
    badge.className = 'activity-status-badge done';
  };
}

function rankJobs() {
  const log   = document.getElementById('activity-log');
  const badge = document.getElementById('activity-status-badge');
  log.textContent = '';
  badge.textContent = 'Running';
  badge.className = 'activity-status-badge running';
  document.getElementById('activity-modal').style.display = 'flex';
  document.getElementById('btn-activity-stop').style.display = 'none';

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/rank`);
  let _done = false;

  ws.onmessage = e => {
    if (e.data.includes('__DONE__')) {
      _done = true;
      ws.close();
      badge.textContent = 'Done';
      badge.className = 'activity-status-badge done';
      loadStats();
      loadJobs();
      return;
    }
    log.textContent += e.data;
    log.scrollTop = log.scrollHeight;
  };

  ws.onerror = () => {
    if (_done) return;
    log.textContent += '\nWebSocket error.\n';
    badge.textContent = 'Error';
    badge.className = 'activity-status-badge done';
  };
}

// ── Query Expansion modal ─────────────────────────────────────────────────────

async function openSuggestModal() {
  document.getElementById('suggest-modal').style.display = 'flex';
  document.getElementById('suggest-loading').style.display = '';
  document.getElementById('suggest-list').style.display   = 'none';
  document.getElementById('suggest-error').style.display  = 'none';
  document.getElementById('btn-suggest-apply').style.display = 'none';

  let data;
  try {
    const r = await fetch('/api/query-expansion/suggest');
    data = await r.json();
  } catch {
    document.getElementById('suggest-loading').style.display = 'none';
    document.getElementById('suggest-error').style.display   = '';
    document.getElementById('suggest-error').textContent     = 'Failed to fetch suggestions.';
    return;
  }

  document.getElementById('suggest-loading').style.display = 'none';
  const list = document.getElementById('suggest-list');
  list.style.display = '';

  if (data.error || !data.queries || !data.queries.length) {
    list.innerHTML = `<p class="suggest-empty">${esc(data.error || 'No suggestions. Apply a few jobs first.')}</p>`;
    return;
  }

  document.getElementById('btn-suggest-apply').style.display = '';
  list.innerHTML = data.queries.map((q, i) => `
    <label class="suggest-item">
      <input type="checkbox" value="${esc(q)}" checked data-idx="${i}">
      <span>${esc(q)}</span>
    </label>`).join('');
}

function closeSuggestModal() {
  document.getElementById('suggest-modal').style.display = 'none';
}

async function applySuggestions() {
  const checked = [...document.querySelectorAll('#suggest-list input[type=checkbox]:checked')].map(cb => cb.value);
  if (!checked.length) { closeSuggestModal(); return; }
  const r = await fetch('/api/query-expansion/apply', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ queries: checked }),
  });
  const d = await r.json();
  closeSuggestModal();
  showToast(`Added ${d.added} search quer${d.added === 1 ? 'y' : 'ies'}.`);
}

// ── Eval Report modal ─────────────────────────────────────────────────────────

async function openEvalModal() {
  document.getElementById('eval-modal').style.display = 'flex';
  document.getElementById('eval-body').innerHTML = '<p class="eval-loading">Loading…</p>';

  let data;
  try {
    const r = await fetch('/api/eval/report');
    data = await r.json();
  } catch {
    document.getElementById('eval-body').innerHTML = '<p class="eval-error">Failed to load report.</p>';
    return;
  }

  const dc = (data.divergence_cases || []).map(d =>
    `<tr class="div-${d.label === 'false_positive' ? 'fp' : 'fn'}">
       <td>${d.label === 'false_positive' ? '⚠ ranked high, rejected' : '⚠ ranked low, applied'}</td>
       <td>${esc(d.title)}</td><td>${esc(d.company)}</td>
       <td>${d.listwise_rank != null ? `#${d.listwise_rank}` : '—'}</td>
     </tr>`).join('');

  document.getElementById('eval-body').innerHTML = `
    <div class="eval-metrics">
      <div class="eval-metric"><span class="em-label">Precision@5</span><span class="em-value">${data.precision_at_5 != null ? (data.precision_at_5 * 100).toFixed(0) + '%' : '—'}</span></div>
      <div class="eval-metric"><span class="em-label">Precision@10</span><span class="em-value">${data.precision_at_10 != null ? (data.precision_at_10 * 100).toFixed(0) + '%' : '—'}</span></div>
      <div class="eval-metric"><span class="em-label">Ranked</span><span class="em-value">${data.total_ranked ?? '—'}</span></div>
      <div class="eval-metric"><span class="em-label">Divergences</span><span class="em-value">${(data.divergence_cases || []).length}</span></div>
    </div>
    ${dc ? `<table class="eval-div-table"><thead><tr><th>Type</th><th>Title</th><th>Company</th><th>Rank</th></tr></thead><tbody>${dc}</tbody></table>` : ''}
    ${!dc ? '<p class="eval-empty">No divergence cases yet — keep using applied/rejected!</p>' : ''}`;
}

function closeEvalModal() {
  document.getElementById('eval-modal').style.display = 'none';
}

// ── Delete jobs modal ─────────────────────────────────────────────────────────

function openDeleteModal() {
  document.getElementById('delete-step-1').style.display = '';
  document.getElementById('delete-step-2').style.display = 'none';
  document.getElementById('delete-modal').style.display = 'flex';
  document.querySelectorAll('.del-status').forEach(c => c.onchange = updateDeleteCount);
  updateDeleteCount();
}

function closeDeleteModal() {
  document.getElementById('delete-modal').style.display = 'none';
}

function _deleteParams() {
  const statuses = [...document.querySelectorAll('.del-status:checked')].map(c => c.value);
  const from = document.getElementById('del-date-from').value;
  const to   = document.getElementById('del-date-to').value;
  const p = new URLSearchParams();
  statuses.forEach(s => p.append('status', s));
  if (from) p.set('date_from', from);
  if (to)   p.set('date_to', to);
  return { params: p, statuses, from, to };
}

async function updateDeleteCount() {
  const { params, statuses } = _deleteParams();
  if (!statuses.length) {
    document.getElementById('del-count').textContent = '0';
    document.getElementById('btn-delete-go').disabled = true;
    return;
  }
  document.getElementById('del-count').textContent = '…';
  const r = await fetch('/api/jobs/count?' + params);
  const d = await r.json();
  document.getElementById('del-count').textContent = d.count;
  document.getElementById('btn-delete-go').disabled = d.count === 0;
}

function deleteStep2() {
  const { statuses, from, to } = _deleteParams();
  const count = document.getElementById('del-count').textContent;
  const statusLabel = statuses.map(s => s.replace('_', '-')).join(', ');
  let msg = `Are you sure you want to delete <strong>${count} jobs</strong>`;
  msg += ` with status: <strong>${statusLabel}</strong>`;
  if (from || to) msg += `, added ${from || '…'} — ${to || '…'}`;
  msg += '?';
  const trainingStatuses = ['applied', 'rejected'];
  if (statuses.some(s => trainingStatuses.includes(s))) {
    msg += '<br><br><span class="delete-warning">⚠️ Applied/rejected jobs are used as training data for scoring. Deleting them will degrade future evaluation quality.</span>';
  }
  document.getElementById('delete-confirm-msg').innerHTML = msg;
  document.getElementById('delete-step-1').style.display = 'none';
  document.getElementById('delete-step-2').style.display = '';
}

function deleteBack() {
  document.getElementById('delete-step-1').style.display = '';
  document.getElementById('delete-step-2').style.display = 'none';
}

async function executeDelete() {
  const { params } = _deleteParams();
  const r = await fetch('/api/jobs?' + params, { method: 'DELETE' });
  const d = await r.json();
  closeDeleteModal();
  loadStats();
  loadJobs();
  showToast(`Deleted ${d.deleted} job(s)`);
}

// ── Backfill modal ────────────────────────────────────────────────────────────

function openBackfillModal() {
  document.getElementById('backfill-log').textContent = '';
  document.getElementById('backfill-progress').style.display = 'none';
  document.getElementById('progress-bar').style.width = '0%';
  document.getElementById('progress-label').textContent = '0 / 0';
  document.getElementById('backfill-modal').style.display = 'flex';
}

function closeBackfillModal() {
  document.getElementById('backfill-modal').style.display = 'none';
}

function startBackfill() {
  const log  = document.getElementById('backfill-log');
  const btn  = document.getElementById('btn-backfill-start');
  const prog = document.getElementById('backfill-progress');
  const bar  = document.getElementById('progress-bar');
  const lbl  = document.getElementById('progress-label');

  log.textContent = '';
  prog.style.display = '';
  btn.disabled = true;
  btn.textContent = 'Running...';

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/backfill`);

  ws.onmessage = e => {
    const line = e.data;
    const m = line.match(/^PROGRESS:(\d+)\/(\d+)/);
    if (m) {
      const cur = parseInt(m[1]), tot = parseInt(m[2]);
      const pct = tot > 0 ? Math.round(cur / tot * 100) : 0;
      bar.style.width = pct + '%';
      lbl.textContent = `${cur} / ${tot}  (${pct}%)`;
      return;
    }
    if (line.includes('__DONE__')) {
      btn.disabled = false;
      btn.textContent = '▶ Start';
      bar.style.width = '100%';
      checkMissingDescriptions();
      loadJobs();
      return;
    }
    log.textContent += line;
    log.scrollTop = log.scrollHeight;
  };

  ws.onerror = () => {
    log.textContent += '\nWebSocket error.\n';
    btn.disabled = false;
    btn.textContent = '▶ Start';
  };
}

async function _loadSources() {
  const r = await fetch('/api/sources');
  _availableSources = await r.json();
  _sourcesMap = Object.fromEntries(_availableSources.map(s => [s.id, s.name]));

  const sel = document.getElementById('source-filter');
  while (sel.options.length > 1) sel.remove(1);
  _availableSources.forEach(s => sel.add(new Option(s.name, s.id)));
}

async function loadJobs() {
  const search   = document.getElementById('search').value;
  const source   = document.getElementById('source-filter').value;
  const params   = new URLSearchParams({ status: currentStatus });
  if (search)   params.set('search', search);
  if (source)   params.set('source', source);

  try {
    const r = await fetch('/api/jobs?' + params);
    ALL_JOBS = await r.json();
  } catch {
    showToast('Failed to load jobs — is the server running?');
    return;
  }
  _buildScoreFilterPanel();
  render();
}


// ── Card rendering ─────────────────────────────────────────────────────────────

function _parseStructured(j) {
  if (!j.structured_data) return null;
  try { return typeof j.structured_data === 'string' ? JSON.parse(j.structured_data) : j.structured_data; }
  catch { return null; }
}

function _renderStructuredBadges(s) {
  if (!s) return '';
  const tags = [];
  const b = (cls, f, label) => {
    const active = _badgeFilters.has(f) ? ' badge-active' : '';
    return `<span class="badge ${cls}${active}" onclick="toggleBadgeFilter('${f}')">${label}</span>`;
  };
  if (s.remote)  tags.push(b('badge-remote',    'remote',              'remote'));
  if (s.hybrid)  tags.push(b('badge-hybrid',    'hybrid',              'hybrid'));
  if (s.seniority && s.seniority !== 'unknown')
    tags.push(b('badge-seniority', `seniority=${s.seniority}`, esc(s.seniority)));
  if (s.company_type && s.company_type !== 'unknown')
    tags.push(b('badge-company',   `company=${s.company_type}`, esc(s.company_type)));
  if (s.product_vs_outsourcing && s.product_vs_outsourcing !== 'unknown')
    tags.push(b('badge-pvo',       `pvo=${s.product_vs_outsourcing}`, esc(s.product_vs_outsourcing)));
  (s.stack || []).slice(0, 4).forEach(t =>
    tags.push(b('badge-stack',     `stack=${t.toLowerCase()}`, esc(t))));
  return tags.length ? `<div class="job-badges">${tags.join('')}</div>` : '';
}

function _renderCard(j) {
  const score    = j.score != null ? j.score.toFixed(1) : '—';
  const sc       = scoreClass(j.score);
  const srcName  = _sourcesMap[j.source] || j.source || '';
  const srcBadge = srcName ? `<span class="source-badge source-${esc(j.source)}">${esc(srcName)}</span>` : '';
  const rankBadge = j.listwise_rank != null ? `<div class="rank-badge">#${j.listwise_rank}</div>` : '';
  const scoreBadge = `<div class="score-badge ${sc}">${score}</div>`;
  const s = _parseStructured(j);
  const reason = j.rank_reason || j.score_reason || '';
  const isSelected = _selectMode && _selected.has(j.id);
  const checkboxHtml = _selectMode
    ? `<div class="job-select-col"><input type="checkbox" class="job-checkbox" data-job-id="${esc(j.id)}" ${isSelected ? 'checked' : ''} onchange="toggleSelect('${esc(j.id)}', this.checked)"></div>`
    : '';
  return `
  <div class="job-card status-${esc(j.status)}${isSelected ? ' job-selected' : ''}" id="card-${esc(j.id)}">
    ${checkboxHtml}<div class="job-card-body">
    <div class="job-header">
      <div class="job-info">
        <a class="job-title" href="${safeUrl(j.url)}" target="_blank">${esc(j.title)}</a>
        <div class="job-sub">${esc(j.company)} &nbsp;&middot;&nbsp; &#128205; ${esc(j.location)} ${srcBadge}</div>
      </div>
      <div class="score-rank-group">${rankBadge}${scoreBadge}</div>
    </div>
    ${_renderStructuredBadges(s)}
    ${reason ? `<div class="job-reason">${esc(reason)}</div>` : ''}
    ${j.rejection_reason ? `<div class="job-rejection-reason">&#128683; ${esc(j.rejection_reason)}</div>` : ''}
    ${j.description ? `
    <div class="job-desc-toggle" onclick="toggleDesc('${esc(j.id)}')">&#9660; Show description</div>
    <div class="job-desc" id="desc-${esc(j.id)}" style="display:none">${esc(j.description)}</div>` : ''}
    <div class="job-footer">
      <span class="status-tag tag-${esc(j.status)}">${esc(j.status)}</span>
      <span class="job-date">${formatDate(j.created_at)}</span>
      <div class="actions">
        <button class="btn btn-reviewed ${j.status === 'reviewed' ? 'active' : ''}"
          onclick="setStatus('${esc(j.id)}', 'reviewed')">Reviewed</button>
        <button class="btn btn-applied ${j.status === 'applied' ? 'active' : ''}"
          onclick="setStatus('${esc(j.id)}', 'applied')">Applied &#10003;</button>
        <button class="btn btn-rejected ${j.status === 'rejected' ? 'active' : ''}"
          onclick="showRejectReason('${esc(j.id)}', this)">Reject &#10007;</button>
      </div>
    </div>
    </div>
  </div>`;
}

// ── Lazy-loading render ────────────────────────────────────────────────────────

function render() {
  if (_lazyObserver) { _lazyObserver.disconnect(); _lazyObserver = null; }

  const sort = document.getElementById('sort').value;
  _lazyJobs = [...ALL_JOBS];
  if (currentStatus !== 'auto_rejected' && currentStatus !== 'all') _lazyJobs = _lazyJobs.filter(j => j.status !== 'auto_rejected');
  if (sort === 'rank') {
    // listwise_rank is a position *within one ranking run's batch* (reset to 1..N every
    // run), so it's not comparable across jobs ranked on different days — sorting by it
    // directly can put a same-day "least bad of a weak batch" job above a genuinely
    // strong match from another day. score is the only value comparable across the whole
    // list (same prompt, every job); rerank_score/embedding_score are real continuous
    // model outputs (not positions) and make reasonable tiebreakers.
    _lazyJobs.sort((a, b) => {
      const scoreDiff = (b.score ?? -1) - (a.score ?? -1);
      if (scoreDiff !== 0) return scoreDiff;
      return (b.rerank_score ?? b.embedding_score ?? -1) - (a.rerank_score ?? a.embedding_score ?? -1);
    });
  }
  if (sort === 'score')   _lazyJobs.sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  if (sort === 'date')    _lazyJobs.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  if (sort === 'company') _lazyJobs.sort((a, b) => (a.company || '').localeCompare(b.company || ''));

  if (_badgeFilters.size) _lazyJobs = _lazyJobs.filter(_matchesBadgeFilters);
  _updateFilterBar();

  document.getElementById('count').textContent = `${_lazyJobs.length} job${_lazyJobs.length !== 1 ? 's' : ''}`;
  _renderedCount = 0;

  const container = document.getElementById('jobs-container');
  container.innerHTML = '';

  if (!_lazyJobs.length) {
    container.innerHTML = '<div class="no-results">No jobs found.</div>';
    return;
  }

  _appendBatch(container);
}

function _appendBatch(container) {
  const batch = _lazyJobs.slice(_renderedCount, _renderedCount + BATCH_SIZE);
  _renderedCount += batch.length;

  const frag = document.createDocumentFragment();
  batch.forEach(j => {
    const tmp = document.createElement('div');
    tmp.innerHTML = _renderCard(j).trim();
    frag.appendChild(tmp.firstChild);
  });
  container.appendChild(frag);

  if (_renderedCount < _lazyJobs.length) {
    const sentinel = document.createElement('div');
    sentinel.className = 'lazy-sentinel';
    container.appendChild(sentinel);

    _lazyObserver = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        _lazyObserver.disconnect();
        _lazyObserver = null;
        sentinel.remove();
        _appendBatch(container);
      }
    }, { rootMargin: '300px' });
    _lazyObserver.observe(sentinel);
  }
}

// ── Description toggle ────────────────────────────────────────────────────────

function toggleDesc(jobId) {
  const el = document.getElementById(`desc-${jobId}`);
  const toggle = el.previousElementSibling;
  const visible = el.style.display !== 'none';
  el.style.display = visible ? 'none' : 'block';
  toggle.textContent = visible ? '▼ Show description' : '▲ Hide description';
}

// ── Reject popover ────────────────────────────────────────────────────────────

function showRejectReason(jobId, btn) {
  document.querySelectorAll('.reject-popover').forEach(el => el.remove());

  const job = ALL_JOBS.find(j => j.id === jobId);
  const existing = (job && job.rejection_reason) ? esc(job.rejection_reason) : '';

  const popover = document.createElement('div');
  popover.className = 'reject-popover';
  popover.innerHTML = `
    <input class="reject-reason-input" type="text" placeholder="Reason, e.g. rate too low, too junior…" value="${existing}">
    <div class="reject-popover-btns">
      <button class="btn-reject-confirm" onclick="confirmReject('${jobId}')">Reject</button>
      <button class="btn-reject-cancel" onclick="document.querySelectorAll('.reject-popover').forEach(el=>el.remove())">Cancel</button>
    </div>`;

  btn.closest('.job-footer').after(popover);
  const input = popover.querySelector('.reject-reason-input');
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') confirmReject(jobId);
    if (e.key === 'Escape') popover.remove();
  });
}

async function confirmReject(jobId) {
  const popover = document.querySelector('.reject-popover');
  const reason = popover ? popover.querySelector('.reject-reason-input').value.trim() : '';
  if (popover) popover.remove();
  await setStatus(jobId, 'rejected', reason);
}

// ── Status update ─────────────────────────────────────────────────────────────

async function setStatus(jobId, status, rejectionReason = null) {
  const body = { status };
  if (status === 'rejected' && rejectionReason !== null) body.rejection_reason = rejectionReason;
  const r = await fetch(`/api/jobs/${jobId}/status`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    showToast('Error saving status — please try again');
    return;
  }

  // Update local data
  const job = ALL_JOBS.find(j => j.id === jobId);
  if (job) {
    job.status = status;
    if (status === 'rejected' && rejectionReason !== null) job.rejection_reason = rejectionReason;
  }

  // Does the job still belong in the current filtered view?
  const belongs = currentStatus === 'all' || status === currentStatus;

  if (!belongs) {
    // Remove from both local arrays
    const ai = ALL_JOBS.findIndex(j => j.id === jobId);
    if (ai !== -1) ALL_JOBS.splice(ai, 1);
    const li = _lazyJobs.findIndex(j => j.id === jobId);
    if (li !== -1) _lazyJobs.splice(li, 1);

    // Animate card out then remove
    const card = document.getElementById(`card-${jobId}`);
    if (card) {
      card.style.transition = 'opacity 0.15s, transform 0.15s';
      card.style.opacity = '0';
      card.style.transform = 'translateX(12px)';
      setTimeout(() => { card.remove(); }, 160);
    }

    document.getElementById('count').textContent =
      `${_lazyJobs.length} job${_lazyJobs.length !== 1 ? 's' : ''}`;
  } else {
    // Refresh just this card in-place
    const card = document.getElementById(`card-${jobId}`);
    if (card && job) {
      const tmp = document.createElement('div');
      tmp.innerHTML = _renderCard(job).trim();
      card.replaceWith(tmp.firstChild);
    }
  }

  loadStats();
  const labels = { reviewed: 'Marked as reviewed', applied: 'Applied ✓', rejected: 'Rejected' };
  showToast(labels[status] || 'Updated');
}

// ── Criteria ──────────────────────────────────────────────────────────────────

const CRITERIA_LABELS = {
  search_query: 'Search Queries',
  title:        'Job Titles',
  location:     'Locations',
  required:     'Required',
  preferred:    'Preferred',
  rejected:     'Auto-reject keywords',
};

async function loadCriteria() {
  const r = await fetch('/api/criteria');
  const all = await r.json();

  const grouped = {};
  all.forEach(c => {
    if (!grouped[c.type]) grouped[c.type] = [];
    grouped[c.type].push(c);
  });

  const grid = document.getElementById('criteria-grid');
  grid.innerHTML = Object.entries(CRITERIA_LABELS).map(([type, label]) => {
    const items = grouped[type] || [];
    const allActive = items.every(c => c.is_active);
    return `
      <div class="criteria-group" data-type="${type}">
        <div class="criteria-group-header">
          <h3>${label}</h3>
          <button class="btn-select-all" onclick="toggleAll('${type}', ${!allActive})">
            ${allActive ? 'Unselect all' : 'Select all'}
          </button>
        </div>
        ${items.map(c => `
          <div class="criteria-item" id="ci-${c.id}">
            <input type="checkbox" id="cb-${c.id}" ${c.is_active ? 'checked' : ''}
              onchange="toggleCriteria(${c.id}, this.checked)">
            <label for="cb-${c.id}" class="${c.is_active ? '' : 'inactive'}">${esc(c.value)}</label>
            <button class="btn-delete" onclick="deleteCriteria(${c.id})" title="Delete">&#x2715;</button>
          </div>
        `).join('')}
        <div class="criteria-add">
          <input type="text" id="add-${type}" placeholder="Add new...">
          <button onclick="addCriteria('${type}')">Add</button>
        </div>
      </div>`;
  }).join('');
}

async function toggleAll(type, active) {
  const group = document.querySelector(`.criteria-group[data-type="${type}"]`);
  const ids = [...group.querySelectorAll('.criteria-item')].map(el => parseInt(el.id.replace('ci-', '')));
  await Promise.all(ids.map(id =>
    fetch(`/api/criteria/${id}/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ active })
    })
  ));
  loadCriteria();
  showToast(active ? 'All enabled' : 'All disabled');
}

async function toggleCriteria(id, active) {
  await fetch(`/api/criteria/${id}/toggle`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ active })
  });
  const label = document.querySelector(`#ci-${id} label`);
  if (label) label.className = active ? '' : 'inactive';
  showToast(active ? 'Enabled' : 'Disabled');
}

async function deleteCriteria(id) {
  await fetch(`/api/criteria/${id}`, { method: 'DELETE' });
  document.getElementById(`ci-${id}`)?.remove();
  showToast('Deleted');
}

async function addCriteria(type) {
  const input = document.getElementById(`add-${type}`);
  const value = input.value.trim();
  if (!value) return;
  const r = await fetch('/api/criteria', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type, value })
  });
  if (r.ok) {
    input.value = '';
    loadCriteria();
    showToast(`Added: ${value}`);
  }
}

document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && e.target.id?.startsWith('add-')) {
    addCriteria(e.target.id.replace('add-', ''));
  }
});

// ── Run modal ─────────────────────────────────────────────────────────────────

function updateLocationsForSources() {
}

function toggleRunSpec(forceOpen) {
  const body  = document.getElementById('run-spec-body');
  const arrow = document.getElementById('run-spec-arrow');
  const log   = document.getElementById('run-log');
  const open  = forceOpen !== undefined ? forceOpen : body.style.display === 'none';
  body.style.display    = open ? '' : 'none';
  arrow.style.transform = open ? '' : 'rotate(-90deg)';
  log.style.display     = open ? 'none' : '';
}

function toggleRunAll(name) {
  const boxes = document.querySelectorAll(`input[name="${name}"]:not(:disabled)`);
  const allChecked = [...boxes].every(b => b.checked);
  boxes.forEach(b => b.checked = !allChecked);
}

async function openRunModal() {
  if (_agentRunning) {
    openActivityModal();
    return;
  }
  document.getElementById('run-modal').style.display = 'flex';
  document.getElementById('run-log').textContent = '';
  toggleRunSpec(true);

  const r = await fetch('/api/criteria');
  const all = await r.json();

  const searchQueryCriteria = all.filter(c => c.type === 'search_query' && c.is_active);
  const titleCriteria       = all.filter(c => c.type === 'title'        && c.is_active);
  const locations           = all.filter(c => c.type === 'location'     && c.is_active);

  // Mirrors the collector's own fallback (collector/runner.py): titles are used
  // as search queries when no search_query criteria are active.
  const usingTitleFallback = !searchQueryCriteria.length && titleCriteria.length > 0;
  const queriesForRun = usingTitleFallback ? titleCriteria : searchQueryCriteria;

  document.getElementById('run-search-queries-title').textContent =
    usingTitleFallback ? 'Search Queries (using Job Titles)' : 'Search Queries';

  document.getElementById('run-search-queries').innerHTML = queriesForRun.map(c => `
    <label class="run-check">
      <input type="checkbox" name="search-query" value="${esc(c.value)}" checked> ${esc(c.value)}
    </label>`).join('');

  document.getElementById('run-locations').innerHTML = locations.map(c => `
    <label class="run-check">
      <input type="checkbox" name="location" value="${esc(c.value)}" checked> ${esc(c.value)}
    </label>`).join('');

  document.getElementById('run-sources').innerHTML = _availableSources.map(s => `
    <label class="run-check">
      <input type="checkbox" name="source" value="${esc(s.id)}" checked> ${esc(s.name)}
    </label>`).join('');

  document.getElementById('run-sources').addEventListener('change', updateLocationsForSources);

  checkAgentStatus();
}

function closeRunModal() {
  document.getElementById('run-modal').style.display = 'none';
  if (agentSocket) {
    agentSocket.close();
    agentSocket = null;
  }
  // Reset start button so it's correct next time modal opens
  const btn = document.getElementById('btn-start');
  btn.textContent = '▶ Start';
  btn.onclick = startAgent;
}

// ── Agent status & activity ───────────────────────────────────────────────────

let _agentRunning = false;
let _activityPollTimer = null;
let _stopping = false;

function stopAgent() {
  _stopping = true;
  fetch('/api/agent/stop', { method: 'POST' }).catch(() => {});
}

async function checkAgentStatus() {
  const r = await fetch('/api/agent/status');
  const s = await r.json();
  const btn     = document.getElementById('btn-start');
  const runBtn  = document.getElementById('btn-run');
  const stopBtn = document.getElementById('btn-activity-stop');
  if (s.running) {
    btn.textContent = '▶ Start';
    btn.onclick = startAgent;
    runBtn.classList.add('running');
    runBtn.textContent = 'Running...';
    if (stopBtn) stopBtn.style.display = '';
  } else {
    btn.textContent = '▶ Start';
    btn.onclick = startAgent;
    runBtn.classList.remove('running');
    runBtn.textContent = '▶ Run Agent';
    if (stopBtn) stopBtn.style.display = 'none';
  }
}

function _updateAgentIndicator(running) {
  const indicator = document.getElementById('agent-indicator');
  const runBtn    = document.getElementById('btn-run');
  const wasRunning = _agentRunning;
  _agentRunning = running;

  indicator.style.display = running ? 'flex' : 'none';
  runBtn.classList.toggle('running', running);
  runBtn.textContent = running ? 'Running...' : '▶ Run Agent';

  if (wasRunning && !running) {
    loadStats();
    loadJobs();
  }
}

function pollAgentStatus() {
  fetch('/api/agent/status')
    .then(r => r.json())
    .then(s => _updateAgentIndicator(s.running))
    .catch(() => {})
    .finally(() => setTimeout(pollAgentStatus, 5000));
}

function openActivityModal() {
  document.getElementById('activity-modal').style.display = 'flex';
  _loadActivityLogs();
}

function closeActivityModal() {
  document.getElementById('activity-modal').style.display = 'none';
  clearTimeout(_activityPollTimer);
  _activityPollTimer = null;
}

function _loadActivityLogs() {
  fetch('/api/agent/logs')
    .then(r => r.json())
    .then(data => {
      const log = document.getElementById('activity-log');
      const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
      log.textContent = data.lines.length ? data.lines.join('\n') : 'No logs yet.';
      if (atBottom) log.scrollTop = log.scrollHeight;

      const badge   = document.getElementById('activity-status-badge');
      const stopBtn = document.getElementById('btn-activity-stop');
      if (_agentRunning) {
        badge.textContent = 'Running';
        badge.className = 'activity-status-badge running';
        if (stopBtn) stopBtn.style.display = '';
        _activityPollTimer = setTimeout(_loadActivityLogs, 2000);
      } else {
        badge.textContent = 'Done';
        badge.className = 'activity-status-badge done';
        if (stopBtn) stopBtn.style.display = 'none';
      }
    })
    .catch(() => {
      if (_agentRunning) {
        _activityPollTimer = setTimeout(_loadActivityLogs, 2000);
      }
    });
}

function startAgent() {
  const days    = document.getElementById('run-days').value || 7;
  const maxJobs = document.getElementById('run-max-jobs').value || null;
  const log     = document.getElementById('run-log');
  const btn     = document.getElementById('btn-start');
  const runBtn  = document.getElementById('btn-run');

  const searchQueries = [...document.querySelectorAll('input[name="search-query"]:checked')].map(el => el.value);
  const locations     = [...document.querySelectorAll('input[name="location"]:checked')].map(el => el.value);
  const sources       = [...document.querySelectorAll('input[name="source"]:checked')].map(el => el.value);

  if (!searchQueries.length || !locations.length) {
    showToast('Select at least one search query and location');
    return;
  }
  if (!sources.length) {
    showToast('Select at least one source');
    return;
  }

  log.textContent = '';
  toggleRunSpec(false);
  btn.textContent = '⏹ Stop';
  btn.onclick = stopAgent;
  runBtn.classList.add('running');
  runBtn.textContent = 'Running...';

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  agentSocket = new WebSocket(`${proto}://${location.host}/ws/agent`);

  agentSocket.onopen = () => {
    _agentRunning = true;
    agentSocket.send(JSON.stringify({
      days:           parseInt(days),
      max_jobs:       maxJobs ? parseInt(maxJobs) : null,
      search_queries: searchQueries,
      locations,
      sources,
    }));
  };

  function _resetStartBtn() {
    btn.textContent = '▶ Start';
    btn.onclick = startAgent;
    runBtn.classList.remove('running');
    runBtn.textContent = '▶ Run Agent';
    document.getElementById('btn-activity-stop').style.display = 'none';
  }

  agentSocket.onmessage = e => {
    if (e.data.includes('__DONE__')) {
      _resetStartBtn();
      _updateAgentIndicator(false);
      loadStats();
      loadJobs();
      return;
    }
    log.textContent += e.data;
    log.scrollTop = log.scrollHeight;
  };

  agentSocket.onerror = () => {
    if (!_stopping) log.textContent += '\nWebSocket error.\n';
    _resetStartBtn();
    _stopping = false;
  };

  agentSocket.onclose = () => { agentSocket = null; };
}

// ── Tab switching ─────────────────────────────────────────────────────────────

document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    const status = tab.dataset.status;
    const isCriteria = status === 'criteria';
    const isCV = status === 'cv';
    const isJobs = !isCriteria && !isCV;
    document.getElementById('jobs-toolbar').style.display   = isJobs ? '' : 'none';
    document.getElementById('jobs-container').style.display = isJobs ? '' : 'none';
    document.getElementById('criteria-panel').style.display = isCriteria ? '' : 'none';
    document.getElementById('cv-panel').style.display       = isCV ? '' : 'none';
    if (isCriteria) loadCriteria();
    else if (isCV)  loadCV();
    else { currentStatus = status; loadJobs(); }
  });
});

// ── CV ────────────────────────────────────────────────────────────────────────

async function loadCV() {
  const r = await fetch('/api/cv');
  const profiles = await r.json();
  const container = document.getElementById('cv-profiles');
  if (!profiles.length) {
    container.innerHTML = '<p class="cv-empty">No CV uploaded yet. Upload one above to enable job scoring.</p>';
    return;
  }
  container.innerHTML = profiles.map(p => {
    const parsed = p.parsed || {};
    const stack  = (parsed.stack || []).join(', ') || '—';
    const active = p.is_active ? '<span class="cv-badge-active">Active</span>' : '';
    const activateBtn = p.is_active ? '' :
      `<button class="btn-cv-activate" onclick="activateCV(${p.id})">Set active</button>`;
    const suggestBtn = p.is_active
      ? `<button class="btn-cv-suggest" onclick="suggestCriteria(${p.id})">Suggest criteria</button>`
      : '';
    return `
    <div class="cv-card ${p.is_active ? 'cv-card-active' : ''}" id="cv-card-${p.id}">
      <div class="cv-card-header">
        <div>
          <span class="cv-filename">${esc(p.filename)}</span>
          ${active}
        </div>
        <div class="cv-card-actions">
          ${activateBtn}
          ${suggestBtn}
        </div>
      </div>
      <div class="cv-fields">
        <div class="cv-field"><span class="cv-label">Seniority</span><span>${esc(parsed.seniority || '—')}</span></div>
        <div class="cv-field"><span class="cv-label">Experience</span><span>${esc(String(parsed.years_experience ?? '—'))} yrs</span></div>
        <div class="cv-field"><span class="cv-label">Location</span><span>${esc(parsed.location || '—')}</span></div>
        <div class="cv-field"><span class="cv-label">Remote</span><span>${esc(parsed.remote_preference || '—')}</span></div>
      </div>
      <div class="cv-stack">${esc(stack)}</div>
      ${parsed.raw_summary ? `<div class="cv-summary">${esc(parsed.raw_summary)}</div>` : ''}
    </div>`;
  }).join('');
}

async function uploadCV() {
  const input  = document.getElementById('cv-file');
  const status = document.getElementById('cv-upload-status');
  const btn    = document.getElementById('btn-cv-upload');
  if (!input.files.length) { showToast('Select a PDF file first'); return; }
  const formData = new FormData();
  formData.append('file', input.files[0]);
  btn.disabled = true;
  btn.textContent = 'Parsing…';
  status.textContent = '';
  try {
    const r = await fetch('/api/cv/upload', { method: 'POST', body: formData });
    const data = await r.json();
    if (!r.ok) {
      status.innerHTML = `<span class="cv-error">${esc(data.error)}</span>`;
    } else {
      input.value = '';
      status.innerHTML = '<span class="cv-ok">CV uploaded and parsed successfully.</span>';
      loadCV();
    }
  } catch (e) {
    status.innerHTML = `<span class="cv-error">Upload failed: ${esc(String(e))}</span>`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Upload & Parse';
  }
}

async function activateCV(id) {
  await fetch(`/api/cv/${id}/activate`, { method: 'POST' });
  loadCV();
  showToast('CV profile activated');
}

async function suggestCriteria(id) {
  const btn = document.querySelector(`#cv-card-${id} .btn-cv-suggest`);
  const panel = document.getElementById('cv-suggestions');
  if (btn) { btn.disabled = true; btn.textContent = 'Generating…'; }
  panel.style.display = 'none';
  try {
    const r = await fetch(`/api/cv/${id}/suggest-criteria`, { method: 'POST' });
    const data = await r.json();
    if (!r.ok) { showToast(data.error || 'Failed to generate suggestions'); return; }

    const renderChecks = (containerId, name, items) => {
      document.getElementById(containerId).innerHTML = (items || []).map(v => `
        <label class="suggest-check">
          <input type="checkbox" name="${name}" value="${esc(v)}" checked> ${esc(v)}
        </label>`).join('');
    };
    renderChecks('suggest-search-queries', 'suggest-search-query', data.search_queries);
    renderChecks('suggest-titles',         'suggest-title',        data.titles);
    renderChecks('suggest-locations',      'suggest-location',     data.locations);
    renderChecks('suggest-required',       'suggest-required',     data.required);
    renderChecks('suggest-preferred',      'suggest-preferred',    data.preferred);

    panel.style.display = '';
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Suggest criteria'; }
  }
}

async function applySuggestions() {
  const checked = name => [...document.querySelectorAll(`input[name="${name}"]:checked`)].map(el => el.value);
  const searchQueries = checked('suggest-search-query');
  const titles        = checked('suggest-title');
  const locations     = checked('suggest-location');
  const required      = checked('suggest-required');
  const preferred     = checked('suggest-preferred');
  if (!searchQueries.length && !titles.length && !locations.length && !required.length && !preferred.length) {
    showToast('Nothing selected'); return;
  }

  const btn = document.getElementById('btn-cv-apply');
  btn.disabled = true;
  btn.textContent = 'Adding…';
  try {
    const r = await fetch('/api/cv/0/apply-criteria', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ search_queries: searchQueries, titles, locations, required, preferred }),
    });
    const data = await r.json();
    if (r.ok) {
      document.getElementById('cv-suggestions').style.display = 'none';
      const total = (data.added_search_queries || 0) + data.added_titles + data.added_locations + data.added_required + data.added_preferred;
      showToast(`Added ${total} criteria to Criteria tab`);
    } else {
      showToast(data.error || 'Failed to apply');
    }
  } finally {
    btn.disabled = false;
    btn.textContent = 'Add selected to Criteria';
  }
}

// ── Search / filter listeners ─────────────────────────────────────────────────

// ── Badge filters ─────────────────────────────────────────────────────────────

function _scoreKey(score) {
  return score != null ? `score=${score.toFixed(1)}` : 'score=none';
}

function _matchesBadgeFilters(j) {
  const active = [..._badgeFilters];
  const scoreFilters = active.filter(f => f.startsWith('score='));
  const otherFilters = active.filter(f => !f.startsWith('score='));

  // Score filters are OR'd against each other (pick any of several exact values);
  // everything else stays AND'd together like before.
  if (scoreFilters.length && !scoreFilters.includes(_scoreKey(j.score))) return false;

  if (!otherFilters.length) return true;
  const s = _parseStructured(j);
  if (!s) return false;
  const stackLower = (s.stack || []).map(t => t.toLowerCase());
  for (const f of otherFilters) {
    if (f === 'remote'  && !s.remote) return false;
    if (f === 'hybrid'  && !s.hybrid) return false;
    if (f.startsWith('seniority=') && s.seniority !== f.slice(10)) return false;
    if (f.startsWith('company=')   && s.company_type !== f.slice(8)) return false;
    if (f.startsWith('pvo=')       && s.product_vs_outsourcing !== f.slice(4)) return false;
    if (f.startsWith('stack=')     && !stackLower.includes(f.slice(6))) return false;
  }
  return true;
}

function _buildScoreFilterPanel() {
  const panel = document.getElementById('score-filter-panel');
  if (!panel) return;
  const counts = new Map();
  for (const j of ALL_JOBS) {
    const key = _scoreKey(j.score);
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  const keys = [...counts.keys()].sort((a, b) => {
    if (a === 'score=none') return 1;
    if (b === 'score=none') return -1;
    return parseFloat(b.slice(6)) - parseFloat(a.slice(6));
  });
  if (!keys.length) {
    panel.innerHTML = '<div class="score-filter-empty">No jobs loaded</div>';
    _updateScoreFilterBadge();
    return;
  }
  const pills = keys.map(key => {
    const isNone = key === 'score=none';
    const rawScore = isNone ? null : parseFloat(key.slice(6));
    const cls = scoreClass(rawScore);
    const label = isNone ? 'n/a' : rawScore.toFixed(1);
    const active = _badgeFilters.has(key) ? ' active' : '';
    return `<span class="score-pill ${cls}${active}" onclick="toggleBadgeFilter('${key}')">${label}<span class="n">${counts.get(key)}</span></span>`;
  }).join('');
  panel.innerHTML = `<div class="score-filter-title">Filter by score</div>` +
    `<div class="score-filter-grid">${pills}</div>` +
    `<button type="button" class="score-filter-clear" onclick="_clearScoreFilters()">Clear score filter</button>`;
  _updateScoreFilterBadge();
}

function _clearScoreFilters() {
  for (const f of [..._badgeFilters]) if (f.startsWith('score=')) _badgeFilters.delete(f);
  _buildScoreFilterPanel();
  render();
}

function _updateScoreFilterBadge() {
  const el = document.getElementById('score-filter-badge');
  if (!el) return;
  const n = [..._badgeFilters].filter(f => f.startsWith('score=')).length;
  el.style.display = n ? '' : 'none';
  el.textContent = n;
}

function toggleScoreFilterPanel(e) {
  e.stopPropagation();
  const panel = document.getElementById('score-filter-panel');
  const opening = panel.style.display === 'none';
  panel.style.display = opening ? 'block' : 'none';
  if (opening) _buildScoreFilterPanel();
}

document.addEventListener('click', (e) => {
  const wrap = document.getElementById('score-filter-wrap');
  const panel = document.getElementById('score-filter-panel');
  if (wrap && panel && !wrap.contains(e.target)) panel.style.display = 'none';
});

function toggleBadgeFilter(f) {
  _badgeFilters.has(f) ? _badgeFilters.delete(f) : _badgeFilters.add(f);
  if (f.startsWith('score=')) _buildScoreFilterPanel(); else _updateScoreFilterBadge();
  render();
}

function removeBadgeFilter(f) {
  _badgeFilters.delete(f);
  if (f.startsWith('score=')) _buildScoreFilterPanel(); else _updateScoreFilterBadge();
  render();
}

function clearBadgeFilters() {
  _badgeFilters.clear();
  _buildScoreFilterPanel();
  render();
}

function _filterLabel(f) {
  if (f === 'remote' || f === 'hybrid') return f;
  if (f.startsWith('score=')) return f.slice(6) === 'none' ? 'score: not scored' : `score: ${f.slice(6)}`;
  return f.includes('=') ? f.split('=')[1] : f;
}

function _updateFilterBar() {
  const bar   = document.getElementById('filter-bar');
  const chips = document.getElementById('filter-chips');
  if (!bar || !chips) return;
  if (!_badgeFilters.size) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';
  chips.innerHTML = [..._badgeFilters].map(f =>
    `<span class="filter-chip">${esc(_filterLabel(f))}<button onclick="removeBadgeFilter('${esc(f)}')" title="Remove">×</button></span>`
  ).join('');
}

// ── Select mode & bulk actions ────────────────────────────────────────────────

function toggleSelectMode() {
  _selectMode = !_selectMode;
  if (!_selectMode) _selected.clear();
  const btn = document.getElementById('btn-select-mode');
  if (btn) { btn.textContent = _selectMode ? '✕ Cancel' : '&#9776; Bulk actions'; btn.classList.toggle('active', _selectMode); }
  const bar = document.getElementById('bulk-bar');
  if (bar) bar.style.display = _selectMode ? 'flex' : 'none';
  render();
}

function toggleSelect(jobId, checked) {
  checked ? _selected.add(jobId) : _selected.delete(jobId);
  const card = document.getElementById(`card-${jobId}`);
  if (card) card.classList.toggle('job-selected', checked);
  _updateBulkBar();
}

function selectAll() {
  _lazyJobs.forEach(j => _selected.add(j.id));
  document.querySelectorAll('.job-checkbox').forEach(cb => {
    cb.checked = true;
    const card = document.getElementById(`card-${cb.dataset.jobId}`);
    if (card) card.classList.add('job-selected');
  });
  _updateBulkBar();
}

function deselectAll() {
  _selected.clear();
  document.querySelectorAll('.job-checkbox').forEach(cb => { cb.checked = false; });
  document.querySelectorAll('.job-selected').forEach(el => el.classList.remove('job-selected'));
  _updateBulkBar();
}

function _updateBulkBar() {
  const n = _selected.size;
  const el = document.getElementById('bulk-count');
  if (el) el.textContent = `${n} selected`;
  document.querySelectorAll('.bulk-action').forEach(btn => { btn.disabled = n === 0; });
}

async function bulkSetStatus(status, reason = '') {
  const ids = [..._selected];
  if (!ids.length) return;
  await Promise.all(ids.map(id =>
    fetch(`/api/jobs/${id}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status, ...(reason ? { rejection_reason: reason } : {}) }),
    })
  ));
  ids.forEach(id => {
    const job = ALL_JOBS.find(j => j.id === id);
    if (job) { job.status = status; if (reason) job.rejection_reason = reason; }
  });
  _selected.clear();
  _updateBulkBar();
  render();
  loadStats();
}

function openBulkRejectModal() {
  if (!_selected.size) return;
  const msg = document.getElementById('bulk-reject-msg');
  if (msg) msg.textContent = `Rejecting ${_selected.size} job${_selected.size > 1 ? 's' : ''}.`;
  const input = document.getElementById('bulk-reject-reason');
  if (input) { input.value = ''; }
  document.getElementById('bulk-reject-overlay').style.display = 'flex';
  setTimeout(() => input && input.focus(), 50);
}

function closeBulkRejectModal() {
  document.getElementById('bulk-reject-overlay').style.display = 'none';
}

function confirmBulkReject() {
  const reason = (document.getElementById('bulk-reject-reason')?.value || '').trim();
  closeBulkRejectModal();
  bulkSetStatus('rejected', reason);
}

// ── Search & filters ──────────────────────────────────────────────────────────

let searchTimeout;
document.getElementById('search').addEventListener('input', () => {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(loadJobs, 300);
});
document.getElementById('source-filter').addEventListener('change', loadJobs);
document.getElementById('sort').addEventListener('change', render);


// ── Preference Profile ────────────────────────────────────────────────────────

function openPrefsModal() {
  document.getElementById('prefs-modal').style.display = 'flex';
  _loadPrefsProfile();
}

function closePrefsModal() {
  document.getElementById('prefs-modal').style.display = 'none';
}

async function _loadPrefsProfile() {
  const meta = document.getElementById('prefs-meta');
  const content = document.getElementById('prefs-content');
  try {
    const r = await fetch('/api/preferences');
    const d = await r.json();
    if (!d.profile) {
      meta.textContent = '';
      content.innerHTML = '<span class="prefs-empty">No profile yet. Click "Refresh" to distill from your feedback history.</span>';
      return;
    }
    const p = d.profile;
    const updated = new Date(p.updated_at.replace(' ', 'T') + 'Z').toLocaleString('pl-PL', {
      day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
    });
    meta.textContent = `Applied: ${p.applied_count} | Rejected: ${p.rejected_count} | Updated: ${updated}`;
    content.textContent = p.content;
  } catch (e) {
    content.textContent = 'Error loading profile.';
  }
}

async function distillPreferences() {
  const btn = document.getElementById('btn-prefs-refresh');
  const content = document.getElementById('prefs-content');
  const meta = document.getElementById('prefs-meta');
  btn.disabled = true;
  btn.textContent = '⏳ Distilling…';
  content.innerHTML = '<span class="prefs-empty">Analyzing feedback history with Claude…</span>';
  meta.textContent = '';
  try {
    const r = await fetch('/api/preferences/distill', { method: 'POST' });
    const d = await r.json();
    if (!r.ok || !d.ok) {
      content.textContent = d.reason || 'Failed to distill.';
      showToast('Distillation failed');
      return;
    }
    content.textContent = d.content;
    meta.textContent = `Applied: ${d.applied_count} | Rejected: ${d.rejected_count} | Updated: now`;
    showToast('Preference profile updated');
  } catch (e) {
    content.textContent = 'Error during distillation.';
    showToast('Error: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '↺ Refresh Profile';
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────

loadStats();
_loadSources().then(loadJobs);
pollAgentStatus();
