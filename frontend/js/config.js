const CONFIG = {
  API_BASE_URL: "http://127.0.0.1:8000/api/v1",
  STORAGE_TOKEN_KEY: "smartCampus.token",
  STORAGE_USER_KEY: "smartCampus.user"
};

// Global DOM Helper
function $(id) {
  return document.getElementById(id);
}

// Global String Sanitizer
function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, function (c) {
    return { '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c];
  });
}

function pad(n) {
  return (n < 10 ? '0' : '') + n;
}

function toLocalInput(d) {
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
         'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}

function fmt(dt) {
  if (!dt) return '—';
  const d = new Date(dt);
  return d.toLocaleString(undefined, {
    weekday: 'short', day: '2-digit', month: 'short',
    hour: '2-digit', minute: '2-digit'
  });
}

function fmtShort(dt) {
  if (!dt) return '—';
  const d = new Date(dt);
  return d.toLocaleString(undefined, {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'
  });
}

function toast(msg, kind = '') {
  const t = $('toast');
  if (!t) return;
  t.textContent = msg;
  t.className = 'toast show ' + kind;
  clearTimeout(t._t);
  t._t = setTimeout(() => {
    t.className = 'toast ' + kind;
  }, 3200);
}

function closeModal() {
  const root = $('modalRoot');
  if (root) root.innerHTML = '';
}

window.$ = $;
window.esc = esc;
window.pad = pad;
window.toLocalInput = toLocalInput;
window.fmt = fmt;
window.fmtShort = fmtShort;
window.toast = toast;
window.closeModal = closeModal;
