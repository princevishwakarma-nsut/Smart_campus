/* =========================================================
   Smart Campus — Application Bootstrap & Event Handlers
   ========================================================= */

window.onerror = function (msg, src, line) {
  const box = document.getElementById('errBanner');
  if (box) {
    box.style.display = 'block';
    box.textContent = 'Script error: ' + msg + ' (line ' + line + ')';
  }
  return false;
};

function $(id) {
  return document.getElementById(id);
}

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

function parseCampusDatetime(value) {
  if (!value) return null;
  const raw = String(value);
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?$/);
  if (match) {
    return new Date(
      Number(match[1]), Number(match[2]) - 1, Number(match[3]),
      Number(match[4]), Number(match[5]), Number(match[6] || 0),
      Number((match[7] || "0").slice(0, 3).padEnd(3, "0"))
    );
  }
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function fmt(dt) {
  if (!dt) return '—';
  const d = parseCampusDatetime(dt);
  if (!d) return '—';
  return d.toLocaleString(undefined, {
    weekday: 'short', day: '2-digit', month: 'short',
    hour: '2-digit', minute: '2-digit'
  });
}

function fmtShort(dt) {
  if (!dt) return '—';
  const d = parseCampusDatetime(dt);
  if (!d) return '—';
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

// Global Application State
const state = {
  view: 'catalog',
  filters: { q: '', category: 'All', date: '', startTime: '', endTime: '' }
};

function render() {
  const viewMeta = VIEWS[state.view] || { title: 'Smart Campus', sub: '' };
  $('viewTitle').textContent = viewMeta.title;
  $('viewSub').textContent = viewMeta.sub;
  $('topActions').innerHTML = '';

  switch (state.view) {
    case 'catalog':
      if (typeof window.renderCatalog === 'function') window.renderCatalog();
      break;
    case 'mybookings':
      if (typeof window.renderMyBookings === 'function') window.renderMyBookings();
      break;
    case 'allbookings':
      if (typeof window.renderAllBookings === 'function') window.renderAllBookings();
      break;
    case 'approvals':
      if (typeof window.renderApprovals === 'function') window.renderApprovals();
      break;
    case 'resources':
      if (typeof window.renderResources === 'function') window.renderResources();
      break;
    case 'adminDash':
      if (typeof window.renderAdminDash === 'function') {
        window.renderAdminDash();
      } else {
        $('view').innerHTML = `<div class="empty">Loading campus overview...</div>`;
        setTimeout(() => { if (typeof window.renderAdminDash === 'function') window.renderAdminDash(); }, 120);
      }
      break;
    case 'facultyDash':
      if (typeof window.renderFacultyDash === 'function') {
        window.renderFacultyDash();
      } else {
        $('view').innerHTML = `<div class="empty">Loading your schedule...</div>`;
        setTimeout(() => { if (typeof window.renderFacultyDash === 'function') window.renderFacultyDash(); }, 120);
      }
      break;
    case 'myschedule':
      if (typeof window.renderMySchedule === 'function') window.renderMySchedule();
      break;
    case 'checkins':
      if (typeof window.renderCheckins === 'function') window.renderCheckins();
      break;
    case 'maintenance':
      if (typeof window.renderMaintenance === 'function') window.renderMaintenance();
      break;
    case 'blackouts':
      if (typeof window.renderBlackouts === 'function') window.renderBlackouts();
      break;
    case 'users':
      if (typeof window.renderUsers === 'function') window.renderUsers();
      break;
    case 'reports':
      if (typeof window.renderReports === 'function') window.renderReports();
      break;
    case 'audit':
      if (typeof window.renderAudit === 'function') window.renderAudit();
      break;
    case 'settings':
      if (typeof window.renderSettings === 'function') {
        window.renderSettings();
      } else {
        $('view').innerHTML = `<div class="empty">Loading system settings...</div>`;
        setTimeout(() => { if (typeof window.renderSettings === 'function') window.renderSettings(); }, 120);
      }
      break;
    case 'bookEquipment':
      if (typeof window.renderBookEquipment === 'function') window.renderBookEquipment();
      break;
    case 'timetableAssignments':
      if (typeof window.renderTimetableAssignments === 'function') window.renderTimetableAssignments();
      break;
    default:
      if (typeof window.renderCatalog === 'function') window.renderCatalog();
  }
}

window.addEventListener('DOMContentLoaded', async () => {
  const token = api.getToken();
  const cachedUser = getCurrentUser();
  if (!token || !cachedUser) {
    api.clearToken();
    setCurrentUser(null);
    showLoginScreen();
    return;
  }

  try {
    setCurrentUser(await api.get("/auth/me"));
    showAppScreen();
  } catch (err) {
    console.error("Could not restore the current tab session:", err);
    showLoginScreen();
  }
});
