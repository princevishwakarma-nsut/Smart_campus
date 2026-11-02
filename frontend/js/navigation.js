const VIEWS = {
  catalog:     { title: "Find a resource",    sub: "Browse spaces, labs, sports facilities and equipment — then request a slot." },
  mybookings:  { title: "My bookings",        sub: "Review all current and past requests, and cancel eligible bookings." },
  facultyDash: { title: "Dashboard",          sub: "Your upcoming approved bookings at a glance." },
  myschedule:  { title: "My schedule",        sub: "" },
  approvals:   { title: "Approval queue",     sub: "Review pending requests and approve or reject them with remarks." },
  adminDash:   { title: "Campus overview",    sub: "Live snapshot of resources, requests and utilization across campus." },
  resources:   { title: "Resource inventory", sub: "Manage the catalogue, status and approval rules." },
  allbookings: { title: "All bookings",       sub: "Every booking request across campus with status and remarks." },
  checkins:    { title: "Check-in Desk",      sub: "Verify attendance, check in/out participants and mark no-shows." },
  maintenance: { title: "Maintenance",        sub: "Take resources out of service and bring them back online." },
  blackouts:   { title: "Blackout Windows",   sub: "Schedule and manage holiday, exam or event closures." },
  users:       { title: "User Management",    sub: "Provision faculty, staff and admin accounts and manage permissions." },
  reports:     { title: "Utilization reports",sub: "Demand, cancellations and peak-hour analytics for planning." },
  audit:                { title: "Audit trail",        sub: "Every booking, resource and settings change is recorded here." },
  settings:             { title: "Settings",           sub: "System-wide booking rules and defaults." },
  bookEquipment:        { title: "Book Equipment",     sub: "Reserve sports and electronic equipment in quantities from the campus Gym." },
  timetableAssignments: { title: "Faculty Timetable",  sub: "Assign active faculty members to academic timetable lectures and lab sessions." }
};

const VIEW_ACCESS = {
  catalog:              () => true,
  mybookings:           () => true,
  facultyDash:          () => isFaculty(),
  myschedule:           () => isFaculty(),
  approvals:            () => canApprove(),
  adminDash:            () => isAdmin(),
  resources:            () => isAdmin(),
  allbookings:          () => isAdmin(),
  checkins:             () => isAdmin() || isStaff(),
  maintenance:          () => isAdmin() || isStaff(),
  blackouts:            () => isAdmin(),
  users:                () => isAdmin(),
  reports:              () => isAdmin(),
  audit:                () => isAdmin(),
  settings:             () => isAdmin(),
  bookEquipment:        () => true,
  timetableAssignments: () => isAdmin()
};

let currentPendingCount = 0;
let lastPendingBookingKey = null;
let lastMyBookingKey = null;
let lastAllBookingKey = null;

function updatePendingBadge(count) {
  currentPendingCount = count;
  renderNav();
}

async function checkBadges() {
  if (document.visibilityState === "hidden" || !api.getToken() || !getCurrentUser()) return;

  if (typeof fetchUnreadNotificationCount === "function") {
    await fetchUnreadNotificationCount();
  }
  if (typeof refreshNotificationPanel === "function") {
    refreshNotificationPanel();
  }
  if (typeof isAdmin === "function" && isAdmin()) {
    try {
      const list = await api.get("/approvals/pending");
      if (list && Array.isArray(list)) {
        const key = list.map(booking => `${booking.booking_id}:${booking.status}`).sort().join("|");
        if (currentPendingCount !== list.length) {
          currentPendingCount = list.length;
          renderNav();
        }
        if (lastPendingBookingKey !== null && key !== lastPendingBookingKey &&
            ["adminDash", "approvals"].includes(state.view)) render();
        lastPendingBookingKey = key;
      }

      if (state.view === "allbookings") {
        const bookings = await api.get("/bookings");
        const key = bookings.map(booking => `${booking.booking_id}:${booking.status}:${booking.updated_at || ""}`).join("|");
        if (lastAllBookingKey !== null && key !== lastAllBookingKey) render();
        lastAllBookingKey = key;
      }
    } catch (err) {
      console.error("Could not refresh booking updates:", err);
    }
  } else if (["mybookings", "myschedule", "facultyDash"].includes(state.view)) {
    try {
      let bookings;
      let scheduleDate = "";
      if (state.view === "myschedule") {
        const schedule = await api.get("/bookings/my/schedule");
        scheduleDate = schedule.today;
        bookings = [...schedule.today_bookings, ...schedule.upcoming_bookings];
      } else {
        bookings = await api.get("/bookings/my");
      }
      const key = `${scheduleDate}|${bookings.map(booking => `${booking.booking_id}:${booking.status}:${booking.updated_at || ""}`).join("|")}`;
      if (lastMyBookingKey !== null && key !== lastMyBookingKey) render();
      lastMyBookingKey = key;
    } catch (err) {
      console.error("Could not refresh your booking updates:", err);
    }
  }
}
window.checkBadges = checkBadges;

if (!window._badgeInterval) {
  window._badgeInterval = setInterval(checkBadges, 15000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") checkBadges();
  });
  window.addEventListener("focus", checkBadges);
}

function navItems() {
  const role = getCurrentUser() ? getCurrentUser().role : "Student";
  if (role === "Student") {
    return [
      { key: "catalog",       label: "Find resources", ico: "⌕" },
      { key: "bookEquipment", label: "Book Equipment", ico: "⚡" },
      { key: "mybookings",    label: "My bookings",    ico: "▤" }
    ];
  }
  if (role === "Faculty") {
    return [
      { key: "facultyDash",   label: "Dashboard",      ico: "⌂" },
      { key: "catalog",       label: "Find resources", ico: "⌕" },
      { key: "bookEquipment", label: "Book Equipment", ico: "⚡" },
      { key: "myschedule",    label: "My schedule",    ico: "▦" },
      { key: "mybookings",    label: "My bookings",    ico: "▤" }
    ];
  }
  if (role === "Staff") {
    return [
      { key: "checkins",      label: "Check-in Desk",  ico: "✓" },
      { key: "catalog",       label: "Find resources", ico: "⌕" },
      { key: "maintenance",   label: "Maintenance",    ico: "⚙" }
    ];
  }
  // Admin
  return [
    { key: "adminDash",            label: "Overview",            ico: "⌂" },
    { key: "resources",            label: "Resource inventory",  ico: "▦" },
    { key: "allbookings",          label: "All bookings",        ico: "▤" },
    { key: "approvals",            label: "Approval queue",      ico: "✓", badge: currentPendingCount },
    { key: "maintenance",          label: "Maintenance",         ico: "⚙" },
    { key: "blackouts",            label: "Blackout Windows",    ico: "⛔" },
    { key: "users",                label: "User Management",     ico: "👥" },
    { key: "reports",              label: "Utilization reports", ico: "▥" },
    { key: "audit",                label: "Audit trail",         ico: "≡" },
    { key: "settings",             label: "Settings",            ico: "⚒" }
  ];
}

function renderNav() {
  const items = navItems();
  let html = "";
  for (const it of items) {
    const isActive = state.view === it.key;
    html += `
      <button type="button" class="${isActive ? 'active' : ''}" onclick="go('${it.key}')">
        <span class="ico">${it.ico}</span>
        <span>${esc(it.label)}</span>
        ${it.badge ? `<span class="badge">${it.badge}</span>` : ""}
      </button>
    `;
  }
  $("nav").innerHTML = html;
}

function go(view) {
  const allowed = VIEW_ACCESS[view];
  if (!allowed || !allowed()) {
    toast("You do not have permission to open that page.", "err");
    return;
  }
  state.view = view;
  renderNav();
  render();
  checkBadges();
}
