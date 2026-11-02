async function renderApprovals() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading pending approvals...</div>`;

  try {
    const list = await api.get("/approvals/pending");
    updatePendingBadge(list.length);

    if (!list.length) {
      host.innerHTML = `
        <div class="empty">
          <p>✓ All caught up! No requests pending approval right now.</p>
        </div>
      `;
      return;
    }

    let html = `
      <div class="panel">
        <div class="panel-head">
          <h3>Pending Requests (${list.length})</h3>
        </div>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Requester</th>
              <th>Resource / Equipment</th>
              <th>Requested Slot</th>
              <th>Purpose</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
    `;

    for (const b of list) {
      const res = b.resources[0] || {};
      const equipmentText = (b.equipment || []).map(item => `${item.item_name} × ${item.requested_quantity}`).join(", ");
      const bookingTarget = res.resource_name || equipmentText || "Campus booking";
      const startTime = b.start_time || res.start_time;
      html += `
        <tr>
          <td><span class="code">BK-${b.booking_id}</span></td>
          <td>
            <div class="cell-strong">${esc(b.user_name)}</div>
            <div class="muted" style="font-size:11px">${esc(b.user_email)}</div>
          </td>
          <td><b>${esc(bookingTarget)}</b><div class="muted" style="font-size:11px">${esc(res.location || b.equipment?.[0]?.location || '')}</div></td>
          <td>${startTime ? fmtShort(startTime) : '—'}</td>
          <td style="max-width:260px">${esc(b.purpose)}</td>
          <td>
            <div class="actions">
              <button class="btn ok sm" type="button" onclick="quickApprove(${b.booking_id})">Approve</button>
              <button class="btn bad sm" type="button" onclick="openRejectModal(${b.booking_id})">Reject</button>
              <button class="btn ghost sm" type="button" onclick="openBookingHistory(${b.booking_id})">History</button>
            </div>
          </td>
        </tr>
      `;
    }

    html += `</tbody></table></div>`;
    host.innerHTML = html;
  } catch (err) {
    host.innerHTML = `<div class="empty">Failed to load approvals: ${esc(err.message)}</div>`;
  }
}

async function quickApprove(bookingId) {
  try {
    await api.post(`/approvals/${bookingId}/approve`, { remarks: "Approved by manager" });
    toast(`Booking BK-${bookingId} approved!`, "ok");
    if (typeof checkBadges === "function") checkBadges();
    if (state.view === "approvals") renderApprovals();
    else if (state.view === "allbookings") renderAllBookings();
  } catch (err) {
    toast("Approval failed: " + err.message, "err");
  }
}

function openRejectModal(bookingId) {
  const modalHtml = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <div class="modal">
        <div class="modal-head">
          <h2>Reject Booking BK-${bookingId}</h2>
          <button class="btn icon" type="button" onclick="closeModal()">✕</button>
        </div>
        <div class="modal-body">
          <label for="rjReason">Reason for rejection *</label>
          <textarea id="rjReason" class="input" rows="3" placeholder="Provide a reason to notify the requester..."></textarea>
          <div class="modal-foot">
            <button class="btn ghost" type="button" onclick="closeModal()">Cancel</button>
            <button class="btn bad" type="button" onclick="confirmReject(${bookingId})">Reject Request</button>
          </div>
        </div>
      </div>
    </div>
  `;
  $("modalRoot").innerHTML = modalHtml;
}

async function confirmReject(bookingId) {
  const reason = $("rjReason").value.trim() || "Rejected by manager";
  try {
    await api.post(`/approvals/${bookingId}/reject`, { remarks: reason });
    closeModal();
    toast(`Booking BK-${bookingId} rejected.`, "ok");
    if (typeof checkBadges === "function") checkBadges();
    if (state.view === "approvals") renderApprovals();
    else if (state.view === "allbookings") renderAllBookings();
  } catch (err) {
    toast("Rejection failed: " + err.message, "err");
  }
}

// Global window registrations
window.renderApprovals = renderApprovals;
window.quickApprove = quickApprove;
window.openRejectModal = openRejectModal;
window.confirmReject = confirmReject;
