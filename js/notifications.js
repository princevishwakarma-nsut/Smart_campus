let notificationPanelOpen = false;
let notificationPanelTab = "unread";
let notificationPanelRequests = 0;
let notificationUnreadCount = 0;
let notificationHistoryHasMore = false;
let notificationHistoryEndKnown = false;

async function fetchUnreadNotificationCount() {
  try {
    const result = await api.get("/notifications/unread-count");
    notificationUnreadCount = result.unread_count;
    const badge = $("notifBadge");
    if (badge) {
      badge.textContent = result.unread_count > 99 ? "99+" : String(result.unread_count);
      badge.style.display = result.unread_count > 0 ? "inline-block" : "none";
    }
    if (notificationPanelOpen) renderNotificationPanelList();
    return result.unread_count;
  } catch (error) {
    console.error("Could not refresh notification count:", error);
    return null;
  }
}

function notificationTitle(notification) {
  const message = notification.message.toLowerCase();
  if (message.includes("new booking request")) return "New booking request";
  if (message.includes("approved")) return "Booking approved";
  if (message.includes("rejected")) return "Booking rejected";
  if (message.includes("cancelled")) return "Booking cancelled";
  if (message.includes("reminder")) return "Booking reminder";
  return notification.type === "Alert" ? "Campus alert" : "Booking update";
}

function renderNotificationEntries(items, isRead) {
  if (!items.length) {
    return `<div class="notification-empty">${isRead ? "No notification history yet." : "You’re all caught up."}</div>`;
  }
  return items.map(notification => {
    const content = `
      <div class="notification-entry-copy">
        <div class="notification-entry-title">${esc(notificationTitle(notification))}</div>
        <div class="notification-entry-message">${esc(notification.message)}</div>
        <div class="notification-entry-meta">
          ${notification.requester_name ? `<span>Requester: ${esc(notification.requester_name)}</span>` : ""}
          ${notification.resource_name ? `<span>Space: ${esc(notification.resource_name)}</span>` : ""}
          ${notification.equipment_name ? `<span>Equipment: ${esc(notification.equipment_name)}</span>` : ""}
          ${notification.booking_id ? `<span>Booking BK-${notification.booking_id}</span>` : ""}
          ${notification.start_time ? `<span>${fmt(notification.start_time)}${notification.end_time ? ` – ${fmtShort(notification.end_time)}` : ""}</span>` : ""}
        </div>
      </div>
      <div class="notification-entry-trail">
        <span class="pill ${notification.type === "Approval" ? "ok" : notification.type === "Alert" ? "bad" : "info"}">${esc(notification.type)}</span>
        <time>${fmtShort(notification.created_at)}</time>
      </div>`;
    return isRead
      ? `<article class="notification-entry is-read">${content}</article>`
      : `<button class="notification-entry is-unread" type="button" onclick="markNotificationRead(${notification.notification_id})">${content}<span class="notification-unread-dot" aria-label="Unread"></span></button>`;
  }).join("");
}

function renderNotificationPanelList() {
  const list = $("notificationPanelList");
  if (!list) return;
  const items = notificationPanelTab === "history" ? window.notificationHistory : window.unreadNotifications;
  list.innerHTML = renderNotificationEntries(items || [], notificationPanelTab === "history") +
    (notificationPanelTab === "history" && notificationHistoryHasMore
      ? `<button class="btn ghost sm notification-load-more" type="button" onclick="loadMoreNotificationHistory()">Load older notifications</button>`
      : "");
  const unreadTab = $("notificationUnreadTab");
  const historyTab = $("notificationHistoryTab");
  if (unreadTab) {
    unreadTab.classList.toggle("active", notificationPanelTab === "unread");
    unreadTab.setAttribute("aria-selected", String(notificationPanelTab === "unread"));
    unreadTab.textContent = `New (${notificationUnreadCount})`;
  }
  if (historyTab) {
    historyTab.classList.toggle("active", notificationPanelTab === "history");
    historyTab.setAttribute("aria-selected", String(notificationPanelTab === "history"));
    historyTab.textContent = `History (${(window.notificationHistory || []).length})`;
  }
}

function setNotificationPanelTab(tab) {
  notificationPanelTab = tab === "history" ? "history" : "unread";
  renderNotificationPanelList();
}

async function refreshNotificationPanel() {
  if (!notificationPanelOpen) return;
  const requestId = ++notificationPanelRequests;
  try {
    const previousHistory = window.notificationHistory || [];
    const [unread, history] = await Promise.all([
      api.get("/notifications", { is_read: false, limit: 100 }),
      api.get("/notifications", { is_read: true, limit: 100 })
    ]);
    if (requestId !== notificationPanelRequests || !notificationPanelOpen) return;
    window.unreadNotifications = unread;
    const latestIds = new Set(history.map(notification => notification.notification_id));
    const olderHistory = previousHistory.filter(notification => !latestIds.has(notification.notification_id));
    window.notificationHistory = [...history, ...olderHistory];
    notificationHistoryHasMore = history.length === 100 && !notificationHistoryEndKnown;
    renderNotificationPanelList();
  } catch (error) {
    console.error("Could not refresh notifications:", error);
    const list = $("notificationPanelList");
    if (list) list.innerHTML = `<div class="notification-empty error">Could not load notifications: ${esc(error.message)}</div>`;
  }
}

async function loadMoreNotificationHistory() {
  const history = window.notificationHistory || [];
  const beforeId = history.length
    ? Math.min(...history.map(notification => notification.notification_id))
    : null;
  try {
    const older = await api.get("/notifications", { is_read: true, limit: 100, before_id: beforeId });
    const knownIds = new Set(history.map(notification => notification.notification_id));
    const newItems = older.filter(notification => !knownIds.has(notification.notification_id));
    window.notificationHistory = [...history, ...newItems];
    notificationHistoryHasMore = older.length === 100;
    notificationHistoryEndKnown = older.length < 100;
    renderNotificationPanelList();
  } catch (error) {
    toast(`Could not load notification history: ${error.message}`, "err");
  }
}

async function openNotificationsModal() {
  notificationPanelOpen = true;
  notificationPanelTab = "unread";
  window.unreadNotifications = [];
  window.notificationHistory = [];
  notificationHistoryHasMore = false;
  notificationHistoryEndKnown = false;
  $("modalRoot").innerHTML = `
    <div class="modal-backdrop notification-backdrop" onclick="if(event.target===this)closeNotificationsPanel()">
      <section class="notification-panel" role="dialog" aria-modal="true" aria-labelledby="notificationPanelTitle">
        <header class="notification-panel-head">
          <div><h2 id="notificationPanelTitle">${isAdmin() ? "Admin notifications" : "Notifications"}</h2><p class="muted">Updates for your account</p></div>
          <button class="btn icon" type="button" aria-label="Close notifications" onclick="closeNotificationsPanel()">✕</button>
        </header>
        <nav class="notification-tabs" role="tablist">
          <button id="notificationUnreadTab" class="active" type="button" role="tab" aria-selected="true" onclick="setNotificationPanelTab('unread')">New</button>
          <button id="notificationHistoryTab" type="button" role="tab" aria-selected="false" onclick="setNotificationPanelTab('history')">History</button>
        </nav>
        <div id="notificationPanelList" class="notification-panel-list"><div class="notification-empty">Loading notifications...</div></div>
        <footer class="notification-panel-foot">
          <button class="btn ghost sm" type="button" onclick="markAllNotificationsRead()">Mark all as read</button>
          <button class="btn primary sm" type="button" onclick="closeNotificationsPanel()">Done</button>
        </footer>
      </section>
    </div>`;
  await Promise.all([fetchUnreadNotificationCount(), refreshNotificationPanel()]);
}

function closeNotificationsPanel() {
  notificationPanelOpen = false;
  notificationPanelRequests += 1;
  closeModal();
}

async function markNotificationRead(notificationId) {
  try {
    await api.patch(`/notifications/${notificationId}/read`);
    await Promise.all([fetchUnreadNotificationCount(), refreshNotificationPanel()]);
  } catch (error) {
    toast(`Could not mark notification as read: ${error.message}`, "err");
  }
}

async function markAllNotificationsRead() {
  try {
    await api.patch("/notifications/read-all");
    await Promise.all([fetchUnreadNotificationCount(), refreshNotificationPanel()]);
  } catch (error) {
    toast(`Could not mark notifications as read: ${error.message}`, "err");
  }
}

window.fetchUnreadNotificationCount = fetchUnreadNotificationCount;
window.openNotificationsModal = openNotificationsModal;
window.closeNotificationsPanel = closeNotificationsPanel;
window.setNotificationPanelTab = setNotificationPanelTab;
window.refreshNotificationPanel = refreshNotificationPanel;
window.loadMoreNotificationHistory = loadMoreNotificationHistory;
window.markNotificationRead = markNotificationRead;
window.markAllNotificationsRead = markAllNotificationsRead;
