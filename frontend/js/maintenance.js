async function renderMaintenance() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading maintenance records...</div>`;

  $("topActions").innerHTML = `
    <button class="btn primary" type="button" onclick="openAddMaintenanceModal()">+ New Maintenance</button>
  `;

  try {
    const list = await api.get("/maintenance");

    let html = `
      <div class="panel">
        <div class="panel-head">
          <h3>Maintenance Logs (${list.length})</h3>
        </div>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Target</th>
              <th>Issue</th>
              <th>Reported By</th>
              <th>Date</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
    `;

    if (!list.length) {
      html += `<tr><td colspan="7" class="empty">No maintenance records logged.</td></tr>`;
    } else {
      for (const m of list) {
        const target = m.resource_name ? `Space: ${esc(m.resource_name)}` : `Item: ${esc(m.item_name || 'Equipment')}`;
        const isResolved = m.status === "Resolved";
        const pillClass = isResolved ? "ok" : "warn";

        html += `
          <tr>
            <td><span class="code">M-${m.maintenance_id}</span></td>
            <td class="cell-strong">${target}</td>
            <td style="max-width:240px">${esc(m.issue_description)}</td>
            <td>${esc(m.reporter_name || 'Staff')}</td>
            <td>${m.reported_at ? fmtShort(m.reported_at) : '—'}</td>
            <td><span class="pill ${pillClass}">${esc(m.status)}</span></td>
            <td>
              ${!isResolved ? `
                <button class="btn ok sm" type="button" onclick="markMaintenanceResolved(${m.maintenance_id})">Mark Resolved</button>
              ` : `<span class="muted" style="font-size:12px">Resolved ${m.resolved_at ? fmtShort(m.resolved_at) : ''}</span>`}
            </td>
          </tr>
        `;
      }
    }

    html += `</tbody></table></div>`;
    host.innerHTML = html;
  } catch (err) {
    host.innerHTML = `<div class="empty">Failed to load maintenance: ${esc(err.message)}</div>`;
  }
}

async function openAddMaintenanceModal() {
  await fetchResources();

  const resOpts = liveResources.map(r =>
    `<option value="${r.resource_id}">${esc(r.resource_name)} (${esc(r.location || '')})</option>`
  ).join("");

  const modalHtml = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <div class="modal">
        <div class="modal-head">
          <h2>Log Space Maintenance</h2>
          <button class="btn icon" type="button" onclick="closeModal()">✕</button>
        </div>
        <div class="modal-body">
          <label for="mRes">Select Resource *</label>
          <select id="mRes" class="input">${resOpts}</select>

          <label for="mIssue">Issue Description *</label>
          <textarea id="mIssue" class="input" rows="3" placeholder="Describe the fault, repair or scheduled servicing..."></textarea>

          <label for="mType">Maintenance Type *</label>
          <select id="mType" class="input">
            <option>Repair</option>
            <option>Inspection</option>
            <option>Damage</option>
            <option>Scheduled Servicing</option>
            <option>Other</option>
          </select>

          <label for="mStart">Blackout Start (Optional)</label>
          <input id="mStart" class="input" type="datetime-local">

          <label for="mEnd">Blackout End (Optional)</label>
          <input id="mEnd" class="input" type="datetime-local">

          <label for="mRemarks">Additional Remarks</label>
          <input id="mRemarks" class="input" placeholder="Notes for staff or vendor">

          <div id="maintenanceConflictReview" class="maintenance-conflict-review hidden" aria-live="polite"></div>
          <div class="modal-foot">
            <button class="btn ghost" type="button" onclick="closeModal()">Cancel</button>
            <button class="btn bad" type="button" onclick="submitMaintenance()">Take Out of Service</button>
          </div>
        </div>
      </div>
    </div>
  `;
  $("modalRoot").innerHTML = modalHtml;
}

async function submitMaintenance(confirmConflicts = false) {
  const resId = Number($("mRes").value);
  const issue = $("mIssue").value.trim();
  const maintenanceType = $("mType").value;
  const start = $("mStart").value || null;
  const end = $("mEnd").value || null;
  const remarks = $("mRemarks").value.trim() || null;

  if (!issue) {
    toast("Issue description is required.", "err");
    return;
  }

  try {
    await api.post("/maintenance", {
      resource_id: resId,
      issue_description: issue,
      maintenance_type: maintenanceType,
      start_datetime: start,
      end_datetime: end,
      remarks: remarks,
      confirm_booking_conflicts: confirmConflicts
    });
    closeModal();
    toast(confirmConflicts
      ? "Maintenance scheduled. Conflicting bookings were preserved and affected users notified."
      : "Maintenance scheduled and blackout period set.", "ok");
    renderMaintenance();
  } catch (err) {
    let detail = null;
    try { detail = JSON.parse(err.message); } catch (_) {}
    if (detail?.requires_confirmation && Array.isArray(detail.conflicts)) {
      const review = $("maintenanceConflictReview");
      review.classList.remove("hidden");
      review.innerHTML = `
        <b>${detail.conflict_count} existing booking conflict(s) on ${esc(detail.resource_name)}.</b>
        <p>Review and explicitly confirm. Existing bookings will not be cancelled automatically.</p>
        <div class="maintenance-conflict-list">${detail.conflicts.map(conflict => `
          <article><b>BK-${conflict.booking_id} · ${esc(conflict.requester_name || "Requester")} · ${esc(conflict.status)}</b>
            <span>${esc(formatDateTime(conflict.start_time))} – ${esc(formatDateTime(conflict.end_time))}</span>
            <small>${esc(conflict.purpose || "")}</small></article>
        `).join("")}</div>
        <button class="btn bad sm" type="button" onclick="submitMaintenance(true)">Confirm maintenance and notify affected users</button>`;
      return;
    }
    toast("Failed to log maintenance: " + err.message, "err");
  }
}

function formatDateTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

async function markMaintenanceResolved(maintId) {
  try {
    await api.patch(`/maintenance/${maintId}/complete`, { remarks: "Servicing completed and verified." });
    toast("Maintenance marked as resolved. Space restored to Available!", "ok");
    renderMaintenance();
  } catch (err) {
    toast("Failed to complete maintenance: " + err.message, "err");
  }
}

// Global window registrations
window.renderMaintenance = renderMaintenance;
window.openAddMaintenanceModal = openAddMaintenanceModal;
window.submitMaintenance = submitMaintenance;
window.markMaintenanceResolved = markMaintenanceResolved;
