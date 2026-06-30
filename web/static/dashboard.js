let ALL_JOBS = [];
let currentStatus = 'all';
let agentSocket = null;

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
  const r = await fetch('/api/stats');
  const s = await r.json();
  document.getElementById('s-total').textContent         = s.total;
  document.getElementById('s-new').textContent           = s.new;
  document.getElementById('s-reviewed').textContent      = s.reviewed;
  document.getElementById('s-applied').textContent       = s.applied;
  document.getElementById('s-rejected').textContent      = s.rejected;
  document.getElementById('s-auto-rejected').textContent = s.auto_rejected;
  document.getElementById('s-avg').textContent           = s.avg_score || '—';
  document.getElementById('last-updated').textContent    = 'Updated: ' + new Date().toLocaleTimeString();
}

async function loadJobs() {
  const search   = document.getElementById('search').value;
  const minScore = document.getElementById('min-score').value;
  const params   = new URLSearchParams({ status: currentStatus });
  if (search)   params.set('search', search);
  if (minScore) params.set('min_score', minScore);

  const r = await fetch('/api/jobs?' + params);
  ALL_JOBS = await r.json();
  render();
}

function render() {
  const sort = document.getElementById('sort').value;
  let jobs = [...ALL_JOBS];

  if (sort === 'score')   jobs.sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  if (sort === 'date')    jobs.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  if (sort === 'company') jobs.sort((a, b) => (a.company || '').localeCompare(b.company || ''));

  document.getElementById('count').textContent = `${jobs.length} job${jobs.length !== 1 ? 's' : ''}`;

  const container = document.getElementById('jobs-container');
  if (!jobs.length) {
    container.innerHTML = '<div class="no-results">No jobs found.</div>';
    return;
  }

  container.innerHTML = jobs.map(j => {
    const score = j.score != null ? j.score.toFixed(1) : '—';
    const sc    = scoreClass(j.score);
    return `
    <div class="job-card status-${esc(j.status)}" id="card-${esc(j.id)}">
      <div class="job-header">
        <div class="job-info">
          <a class="job-title" href="${safeUrl(j.url)}" target="_blank">${esc(j.title)}</a>
          <div class="job-sub">${esc(j.company)} &nbsp;&middot;&nbsp; &#128205; ${esc(j.location)}</div>
        </div>
        <div class="score-badge ${sc}">${score}</div>
      </div>
      ${j.score_reason ? `<div class="job-reason">${esc(j.score_reason)}</div>` : ''}
      <div class="job-footer">
        <span class="status-tag tag-${esc(j.status)}">${esc(j.status)}</span>
        <span class="job-date">${formatDate(j.created_at)}</span>
        <div class="actions">
          <button class="btn btn-reviewed ${j.status === 'reviewed' ? 'active' : ''}"
            onclick="setStatus('${esc(j.id)}', 'reviewed')">Reviewed</button>
          <button class="btn btn-applied ${j.status === 'applied' ? 'active' : ''}"
            onclick="setStatus('${esc(j.id)}', 'applied')">Applied &#10003;</button>
          <button class="btn btn-rejected ${j.status === 'rejected' ? 'active' : ''}"
            onclick="setStatus('${esc(j.id)}', 'rejected')">Reject &#10007;</button>
        </div>
      </div>
    </div>`;
  }).join('');
}

async function setStatus(jobId, status) {
  const r = await fetch(`/api/jobs/${jobId}/status`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status })
  });
  if (r.ok) {
    const job = ALL_JOBS.find(j => j.id === jobId);
    if (job) job.status = status;
    render();
    loadStats();
    const labels = { reviewed: 'Marked as reviewed', applied: 'Marked as applied', rejected: 'Rejected' };
    showToast(labels[status] || 'Updated');
  }
}

const CRITERIA_LABELS = {
  title:     'Job Titles',
  location:  'Locations',
  required:  'Required',
  preferred: 'Preferred',
  rejected:  'Auto-reject keywords',
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

function toggleRunAll(name) {
  const boxes = document.querySelectorAll(`input[name="${name}"]`);
  const allChecked = [...boxes].every(b => b.checked);
  boxes.forEach(b => b.checked = !allChecked);
}

async function openRunModal() {
  document.getElementById('run-modal').style.display = 'flex';
  document.getElementById('run-log').textContent = '';

  const r = await fetch('/api/criteria');
  const all = await r.json();

  const titles    = all.filter(c => c.type === 'title'    && c.is_active);
  const locations = all.filter(c => c.type === 'location' && c.is_active);

  document.getElementById('run-titles').innerHTML = titles.map(c => `
    <label class="run-check">
      <input type="checkbox" name="title" value="${esc(c.value)}" checked> ${esc(c.value)}
    </label>`).join('');

  document.getElementById('run-locations').innerHTML = locations.map(c => `
    <label class="run-check">
      <input type="checkbox" name="location" value="${esc(c.value)}" checked> ${esc(c.value)}
    </label>`).join('');

  checkAgentStatus();
}

function closeRunModal() {
  document.getElementById('run-modal').style.display = 'none';
  if (agentSocket) {
    agentSocket.close();
    agentSocket = null;
  }
}

async function checkAgentStatus() {
  const r = await fetch('/api/agent/status');
  const s = await r.json();
  const btn    = document.getElementById('btn-start');
  const runBtn = document.getElementById('btn-run');
  if (s.running) {
    btn.disabled = true;
    btn.textContent = 'Running...';
    runBtn.classList.add('running');
    runBtn.textContent = 'Running...';
  } else {
    btn.disabled = false;
    btn.textContent = 'Start';
    runBtn.classList.remove('running');
    runBtn.textContent = 'Run Agent';
  }
}

function startAgent() {
  const days    = document.getElementById('run-days').value || 7;
  const maxJobs = document.getElementById('run-max-jobs').value || null;
  const log     = document.getElementById('run-log');
  const btn     = document.getElementById('btn-start');
  const runBtn  = document.getElementById('btn-run');

  const titles    = [...document.querySelectorAll('input[name="title"]:checked')].map(el => el.value);
  const locations = [...document.querySelectorAll('input[name="location"]:checked')].map(el => el.value);

  if (!titles.length || !locations.length) {
    showToast('Select at least one title and location');
    return;
  }

  log.textContent = '';
  btn.disabled = true;
  btn.textContent = 'Running...';
  runBtn.classList.add('running');
  runBtn.textContent = 'Running...';

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  agentSocket = new WebSocket(`${proto}://${location.host}/ws/agent`);

  agentSocket.onopen = () => {
    agentSocket.send(JSON.stringify({
      days:      parseInt(days),
      max_jobs:  maxJobs ? parseInt(maxJobs) : null,
      titles,
      locations
    }));
  };

  agentSocket.onmessage = e => {
    if (e.data.includes('__DONE__')) {
      btn.disabled = false;
      btn.textContent = 'Start';
      runBtn.classList.remove('running');
      runBtn.textContent = 'Run Agent';
      loadStats();
      loadJobs();
      return;
    }
    log.textContent += e.data;
    log.scrollTop = log.scrollHeight;
  };

  agentSocket.onerror = () => {
    log.textContent += '\nWebSocket error.\n';
    btn.disabled = false;
    btn.textContent = 'Start';
  };

  agentSocket.onclose = () => { agentSocket = null; };
}

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

// --- CV ---

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
    return `
    <div class="cv-card ${p.is_active ? 'cv-card-active' : ''}" id="cv-card-${p.id}">
      <div class="cv-card-header">
        <div>
          <span class="cv-filename">${esc(p.filename)}</span>
          ${active}
        </div>
        ${activateBtn}
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

let searchTimeout;
document.getElementById('search').addEventListener('input', () => {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(loadJobs, 300);
});
document.getElementById('min-score').addEventListener('change', loadJobs);
document.getElementById('sort').addEventListener('change', render);

loadStats();
loadJobs();
