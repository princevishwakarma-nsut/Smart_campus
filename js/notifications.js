async function fetchUnreadNotificationCount() {
  try {
    const res = await api.get("/notifications/unread-count");
    // Update badge if an indicator exists
    const badge = $("notifBadge");
    if (badge) {
      if (res.unread_count > 0) {
        badge.textContent = res.unread_count;
        badge.style.display = "inline-block";
      } else {
        badge.style.display = "none";
      }
    }
    return res.unread_count;
  } catch (e) {
    return 0;
  }
}

async function openNotificationsModal() {
  try {
    const notifs = await api.get("/notifications");

    let listHtml = "";
    if (notifs.length) {
      listHtml = notifs.map(n => `
        <div class="slot" style="margin-bottom:8px">
          <time>${fmtShort(n.created_at)}</time>
          <div>
            <div class="t">${esc(n.message)}</div>
            <div class="s"><span class="pill ${n.type==='Approval'?'ok':(n.type==='Alert'?'bad':'info')}">${esc(n.type)}</span></div>
          </div>
        </div>
      `).join("");
    } else {
      listHtml = `<div class="empty">No notifications yet.</div>`;
    }

    const modalHtml = `
      <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
        <div class="modal">
          <div class="modal-head">
            <h2>${isAdmin() ? "Admin notifications" : "My notifications"}</h2>
            <button class="btn icon" type="button" onclick="closeModal()">&times;</button>
          </div>
          <div class="modal-body">
            <div style="display:flex;justify-content:flex-end;margin-bottom:12px">
              <button class="btn ghost sm" type="button" onclick="markAllNotificationsRead()">Mark all as read</button>
            </div>
            <div class="schedule">${listHtml}</div>
            <div class="modal-foot">
              <button class="btn ghost" type="button" onclick="closeModal()">Close</button>
            </div>
          </div>
        </div>
      </div>
    `;
    $("modalRoot").innerHTML = modalHtml;
  } catch (err) {
    toast("Failed to load notifications: " + err.message, "err");
  }
}

async function markAllNotificationsRead() {
  try {
    await api.patch("/notifications/read-all");
    toast("All notifications marked as read.", "ok");
    fetchUnreadNotificationCount();
    openNotificationsModal();
  } catch (err) {
    toast("Error: " + err.message, "err");
  }
}

// Global window registrations
window.fetchUnreadNotificationCount = fetchUnreadNotificationCount;
window.openNotificationsModal = openNotificationsModal;
window.markAllNotificationsRead = markAllNotificationsRead;
