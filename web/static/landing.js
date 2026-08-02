function toggleTheme() {
  const root = document.documentElement;
  const current = root.getAttribute('data-theme')
    || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  root.setAttribute('data-theme', current === 'dark' ? 'light' : 'dark');
}

document.addEventListener('click', (e) => {
  document.querySelectorAll('details.nav-menu[open]').forEach(menu => {
    if (!menu.contains(e.target)) menu.removeAttribute('open');
  });
});
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  document.querySelectorAll('details.nav-menu[open]').forEach(menu => menu.removeAttribute('open'));
});

async function _uploadCv(file) {
  const dropzone = document.getElementById('dropzone');
  const dropzoneText = document.getElementById('dropzone-text');
  const errorEl = document.getElementById('hero-error');
  errorEl.classList.remove('is-visible');
  dropzone.classList.add('is-busy');
  dropzoneText.innerHTML = '<strong>Reading your CV…</strong><span>This takes a few seconds</span>';

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/api/cv/upload', { method: 'POST', body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Upload failed');
    window.location.href = '/questionnaire';
  } catch (err) {
    dropzone.classList.remove('is-busy');
    dropzoneText.innerHTML = '<strong>Upload your CV</strong><span>PDF · drag and drop, or click to choose a file</span>';
    errorEl.textContent = err.message;
    errorEl.classList.add('is-visible');
    document.getElementById('cv-file').value = '';
  }
}

document.getElementById('cv-file').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (file) _uploadCv(file);
});

// The dropzone's copy has always claimed drag-and-drop support, but no
// listeners actually implemented it — dropping a file just let the browser's
// default behavior take over (navigating the tab to open the PDF directly),
// which looks exactly like the app broke.
const _dropzoneEl = document.getElementById('dropzone');
['dragenter', 'dragover'].forEach(evt => {
  _dropzoneEl.addEventListener(evt, (e) => {
    e.preventDefault();
    if (!_dropzoneEl.classList.contains('is-busy')) _dropzoneEl.classList.add('is-dragover');
  });
});
['dragleave', 'dragend'].forEach(evt => {
  _dropzoneEl.addEventListener(evt, () => _dropzoneEl.classList.remove('is-dragover'));
});
_dropzoneEl.addEventListener('drop', (e) => {
  e.preventDefault();
  _dropzoneEl.classList.remove('is-dragover');
  if (_dropzoneEl.classList.contains('is-busy')) return;
  const file = e.dataTransfer.files[0];
  if (file) _uploadCv(file);
});
