let liveBookings = [];
const bookingPageState = {
  my: { page: 1, total: 0 },
  all: { page: 1, total: 0 }
};

async function fetchMyBookings() {
  try {
    liveBookings = await api.get("/bookings/my");
    return liveBookings;
  } catch (err) {
    toast("Failed to load your bookings: " + err.message, "err");
    return [];
  }
}

async function fetchAllBookings(status = null) {
  try {
    const params = status && status !== "All" ? { status } : {};
    liveBookings = await api.get("/bookings", params);
    return liveBookings;
  } catch (err) {
    toast("Failed to load bookings: " + err.message, "err");
    return [];
  }
}

async function openBookingModal(resourceId) {
  const r = getResourceById(resourceId);
  if (!r) {
    toast("Resource not found", "err");
    return;
  }

  // Pre-fill default dates (Tomorrow 10:00 to 12:00)
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const defaultDate = toLocalInput(tomorrow).split("T")[0];
  const defaultStart = `${defaultDate}T10:00`;
  const defaultEnd = `${defaultDate}T12:00`;

  // Fetch available equipment, societies, and users
  let equipmentList = [];
  let societiesList = [];
  let usersList = [];
  try {
    const [eq, soc, us] = await Promise.all([
      api.get("/equipment", { availability_status: "Available" }).catch(() => []),
      api.get("/societies").catch(() => []),
      api.get("/users").catch(() => [])
    ]);
    equipmentList = eq || [];
    societiesList = soc || [];
    usersList = us || [];
  } catch (e) {}

  const modalHtml = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <div class="modal card" style="max-width:540px;margin:auto;">
        <div class="modal-head" style="display:flex;justify-content:space-between;align-items:center;">
          <div>
            <h3>Book ${esc(r.resource_name)}</h3>
            <p class="sub" style="margin:0;">${esc(r.location || '')} · ${esc(r.category_name || '')}</p>
          </div>
          <button class="btn ghost sm" type="button" onclick="closeModal()">✕</button>
        </div>
        <div class="modal-body" style="margin-top:14px;">
          <div class="form-grid">
          <div class="field">
            <label for="bmStart">Start Date &amp; Time *</label>
            <input id="bmStart" class="input" type="datetime-local" value="${defaultStart}" onchange="checkModalSlotAvailability(${resourceId})">
          </div>

          <div class="field">
            <label for="bmEnd">End Date &amp; Time *</label>
            <input id="bmEnd" class="input" type="datetime-local" value="${defaultEnd}" onchange="checkModalSlotAvailability(${resourceId})">
          </div>
          </div>

          <div id="slotFeedback" class="hint neutral" style="margin-top:8px">
            Checking timetable &amp; booking availability...
          </div>

          <div class="field">
            <label for="bmPurpose">Purpose / Event Description *</label>
            <textarea id="bmPurpose" class="input" rows="2" placeholder="e.g. Guest lecture on AI, society rehearsal, lab practical"></textarea>
          </div>

          ${societiesList.length ? `
            <div class="field">
              <label for="bmSociety">Booking on Behalf of Society (Optional)</label>
              <select id="bmSociety" class="input">
                <option value="">-- Personal / Departmental Booking --</option>
                ${societiesList.map(s => `<option value="${s.club_id}">${esc(s.club_name)}</option>`).join("")}
              </select>
            </div>
          ` : ""}

          <div class="field">
            <label for="bmParts">Expected Participants</label>
            <input id="bmParts" class="input" type="number" min="1" value="1" placeholder="Number of attendees">
          </div>

          ${usersList.length ? `
            <div class="field">
              <label for="bmParticipants">Add Registered Participants (Optional)</label>
              <select id="bmParticipants" class="input" multiple size="3">
                ${usersList.map(u => `<option value="${u.user_id}">${esc(u.full_name)} (${esc(u.email)})</option>`).join("")}
              </select>
              <span class="muted" style="font-size:11px;">Hold Ctrl / Cmd to select attendees for check-in attendance.</span>
            </div>
          ` : ""}

          ${equipmentList.length ? `
            <div class="field">
              <label for="bmEquip">Request Equipment (Optional)</label>
              <select id="bmEquip" class="input" multiple size="3">
                ${equipmentList.map(eq => `<option value="${eq.item_id}">${esc(eq.item_name)} (${esc(eq.condition_status)})</option>`).join("")}
              </select>
              <span class="muted" style="font-size:11px;">Reserved for this session; marked Issued only upon physical handover.</span>
            </div>
          ` : ""}

          <div class="modal-foot" style="display:flex;justify-content:flex-end;gap:8px;margin-top:20px;">
            <button class="btn ghost sm" type="button" onclick="closeModal()">Cancel</button>
            <button id="bmSubmitBtn" class="btn primary sm" type="button" onclick="submitBooking(${resourceId})">Submit Request</button>
          </div>
        </div>
      </div>
    </div>
  `;
  $("modalRoot").innerHTML = modalHtml;
  checkModalSlotAvailability(resourceId);
}

async function checkModalSlotAvailability(resourceId) {
  const startEl = $("bmStart");
  const endEl = $("bmEnd");
  const feedback = $("slotFeedback");
  const submitBtn = $("bmSubmitBtn");
  if (!startEl || !endEl || !feedback) return;

  const startVal = startEl.value;
  const endVal = endEl.value;

  if (!startVal || !endVal) {
    feedback.className = "hint neutral";
    feedback.textContent = "Please choose both a start and an end time.";
    return;
  }

  // Cross-midnight check
  const startDate = startVal.split("T")[0];
  const endDate = endVal.split("T")[0];
  if (startDate !== endDate) {
    feedback.className = "hint bad";
    feedback.textContent = "✗ Bookings crossing midnight are prohibited. Please book each day separately.";
    if (submitBtn) submitBtn.disabled = true;
    return;
  }

  if (new Date(startVal) >= new Date(endVal)) {
    feedback.className = "hint bad";
    feedback.textContent = "✗ Start time must be before end time.";
    if (submitBtn) submitBtn.disabled = true;
    return;
  }

  feedback.className = "hint neutral";
  feedback.textContent = "Checking timetable and room conflicts...";

  try {
    const res = await api.get("/timetable/check", {
      resource_id: resourceId,
      start_time: startVal,
      end_time: endVal
    });

    if (res.is_available) {
      feedback.className = "hint ok";
      feedback.textContent = "✓ Space is available for the selected slot!";
      if (submitBtn) submitBtn.disabled = false;
    } else {
      feedback.className = "hint bad";
      feedback.textContent = "✗ " + (res.reason || "Slot conflict detected.");
      if (submitBtn) submitBtn.disabled = true;
    }
  } catch (err) {
    feedback.className = "hint bad";
    feedback.textContent = "Unable to check availability: " + err.message;
  }
}

async function submitBooking(resourceId) {
  const startVal = $("bmStart").value;
  const endVal = $("bmEnd").value;
  const purpose = $("bmPurpose").value.trim();
  const parts = parseInt($("bmParts").value, 10) || 1;

  if (!purpose) {
    toast("Please enter the purpose of the booking.", "err");
    return;
  }

  // Cross-midnight check
  if (startVal.split("T")[0] !== endVal.split("T")[0]) {
    toast("Bookings crossing midnight are prohibited.", "err");
    return;
  }

  const equipSelect = $("bmEquip");
  let equipIds = [];
  if (equipSelect) {
    equipIds = Array.from(equipSelect.selectedOptions).map(opt => Number(opt.value));
  }

  const socEl = $("bmSociety");
  const societyId = (socEl && socEl.value) ? parseInt(socEl.value, 10) : null;

  const partSelect = $("bmParticipants");
  let participants = [];
  if (partSelect) {
    participants = Array.from(partSelect.selectedOptions).map(opt => ({
      user_id: Number(opt.value),
      participant_role: "Participant"
    }));
  }

  const payload = {
    resource_id: resourceId,
    start_time: startVal,
    end_time: endVal,
    purpose: purpose,
    expected_participants: parts,
    society_id: societyId,
    participants: participants.length ? participants : null,
    equipment_ids: equipIds.length ? equipIds : null
  };

  const btn = $("bmSubmitBtn");
  if (btn) btn.disabled = true;

  try {
    const res = await api.post("/bookings", payload);
    closeModal();
    toast(`Booking request BK-${res.booking_id} submitted! Awaiting Admin approval.`, "ok");
    if (typeof checkBadges === "function") checkBadges();
    if (state.view === "mybookings") {
      renderMyBookings();
    } else {
      go("mybookings");
    }
  } catch (err) {
    toast("Booking failed: " + err.message, "err");
    if (btn) btn.disabled = false;
  }
}

async function renderMyBookings() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading your bookings...</div>`;
  await renderBookingPage("my");
}

async function renderAllBookings() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading all campus bookings...</div>`;
  await renderBookingPage("all");
}

async function renderBookingPage(kind) {
  const statePage = bookingPageState[kind];
  if (!liveCategories.length && typeof fetchCategories === "function") await fetchCategories();
  const offset = (statePage.page - 1) * 20;
  const params = {
    offset,
    limit: 20,
    sort_by: $(`${kind}BkSort`)?.value || "created_desc"
  };
  const status = $(`${kind}BkStatus`)?.value || "All";
  const bookingType = $(`${kind}BkType`)?.value || "All";
  const categoryId = $(`${kind}BkCategory`)?.value || "";
  const q = $(`${kind}BkSearch`)?.value.trim();
  const from = $(`${kind}BkFrom`)?.value;
  const to = $(`${kind}BkTo`)?.value;
  if (from && to && from > to) {
    toast("The start date must be on or before the end date.", "err");
    return;
  }
  if (status !== "All") params.status = status;
  if (bookingType !== "All") params.booking_type = bookingType;
  if (categoryId) params.category_id = categoryId;
  if (q) params.q = q;
  if (from) params.start_date = from;
  if (to) params.end_date = to;

  try {
    const result = await api.get("/bookings/page", params);
    statePage.total = result.total;
    const bookings = result.items;
    const activeFilters = [status !== "All", bookingType !== "All", Boolean(categoryId), Boolean(q), Boolean(from), Boolean(to)].filter(Boolean).length;
    const categoryOptions = (liveCategories || []).map(category => `
      <option value="${category.category_id}" ${String(category.category_id) === categoryId ? "selected" : ""}>${esc(category.category_name)}</option>
    `).join("");
    const controls = `
      <header class="booking-list-heading">
        <div><h2>${kind === "all" ? "Campus bookings" : "My bookings"}</h2><p class="muted">Search and filter your complete booking history.</p></div>
        <span class="booking-count">${result.total} ${result.total === 1 ? "booking" : "bookings"}</span>
      </header>
      <div class="booking-toolbar" aria-label="Booking filters">
          <input id="${kind}BkSearch" class="input sm booking-search" value="${esc(q || "")}" placeholder="Search bookings..." aria-label="Search bookings" onchange="changeBookingFilters('${kind}')">
          <select id="${kind}BkStatus" class="input sm" aria-label="Booking status" onchange="changeBookingFilters('${kind}')">
            ${["All","Pending","Approved","Rejected","Cancelled"].map(value => `<option ${status === value ? "selected" : ""}>${value}</option>`).join("")}
          </select>
          <select id="${kind}BkType" class="input sm" aria-label="Booking type" onchange="changeBookingFilters('${kind}')">
            ${["All","Space","Equipment","Combined"].map(value => `<option ${bookingType === value ? "selected" : ""}>${value}</option>`).join("")}
          </select>
          <select id="${kind}BkCategory" class="input sm" aria-label="Resource category" onchange="changeBookingFilters('${kind}')">
            <option value="">All resource categories</option>${categoryOptions}
          </select>
          <input id="${kind}BkFrom" class="input sm" type="date" value="${esc(from || "")}" aria-label="From date" onchange="changeBookingFilters('${kind}')">
          <input id="${kind}BkTo" class="input sm" type="date" value="${esc(to || "")}" aria-label="To date" onchange="changeBookingFilters('${kind}')">
          <select id="${kind}BkSort" class="input sm" aria-label="Sort bookings" onchange="changeBookingFilters('${kind}', false)">
            <option value="created_desc" ${params.sort_by === "created_desc" ? "selected" : ""}>Newest first</option>
            <option value="created_asc" ${params.sort_by === "created_asc" ? "selected" : ""}>Oldest first</option>
            <option value="start_asc" ${params.sort_by === "start_asc" ? "selected" : ""}>Schedule earliest</option>
            <option value="start_desc" ${params.sort_by === "start_desc" ? "selected" : ""}>Schedule latest</option>
          </select>
          ${activeFilters ? `<button class="btn ghost sm" type="button" onclick="clearBookingFilters('${kind}')">Clear filters (${activeFilters})</button>` : ""}
      </div>`;
    const rows = bookings.map(booking => {
      const firstResource = booking.resources[0] || {};
      const equipmentNames = (booking.equipment || []).map(item => `${item.item_name} × ${item.requested_quantity}`).join(", ");
      const resources = (booking.resources || []).map(resource => resource.resource_name).filter(Boolean).join(", ");
      const locationLabel = resources || equipmentNames || "No linked resources";
      const start = booking.start_time || firstResource.start_time;
      const end = booking.end_time || firstResource.end_time;
      const locations = [...new Set((booking.resources || []).map(resource => resource.location).filter(Boolean))].join(", ");
      const statusClass = booking.status === "Approved" ? "ok" : (booking.status === "Pending" ? "warn" : "bad");
      if (kind === "my") {
        return `<article class="card booking-card">
          <div class="card-head"><div><span class="code">BK-${booking.booking_id}</span><h3>${esc(locationLabel)}</h3></div><span class="pill ${statusClass}">${esc(booking.status)}</span></div>
          <p class="booking-purpose">${esc(booking.purpose)}</p>
          <div class="booking-meta">
            <span><b>When</b>${start ? `${fmt(start)}${end ? ` – ${fmtShort(end)}` : ""}` : "Not scheduled"}</span>
            ${locations ? `<span><b>Location</b>${esc(locations)}</span>` : ""}
            <span><b>Requested</b>${booking.created_at ? fmt(booking.created_at) : "—"}</span>
          </div>
          ${equipmentNames ? `<div class="booking-equipment">Equipment: ${esc(equipmentNames)}</div>` : ""}
          ${booking.remarks ? `<div class="booking-decision">Decision: ${esc(booking.remarks)}</div>` : ""}
          <div class="card-foot">
            <button class="btn ghost sm" type="button" onclick="openBookingDetails(${booking.booking_id})">Details</button>
            ${booking.status === "Pending" || booking.status === "Approved" ? `<button class="btn bad sm" type="button" onclick="openCancelModal(${booking.booking_id})">Cancel</button>` : ""}
          </div>
        </article>`;
      }
      return `<tr>
        <td><span class="code">BK-${booking.booking_id}</span></td>
        <td><div class="cell-strong">${esc(booking.user_name || "—")}</div><div class="muted" style="font-size:11px">${esc(booking.user_email || "")}</div></td>
        <td>${esc(locationLabel)}</td><td>${start ? fmtShort(start) : "—"}</td>
        <td>${esc(booking.purpose)}</td><td><span class="pill ${statusClass}">${esc(booking.status)}</span></td>
        <td><div class="actions">
          <button class="btn ghost sm" type="button" onclick="openBookingHistory(${booking.booking_id})">Trail</button>
          ${booking.status === "Pending" ? `<button class="btn ok sm" type="button" onclick="quickApprove(${booking.booking_id})">Approve</button><button class="btn bad sm" type="button" onclick="openRejectModal(${booking.booking_id})">Reject</button>` : ""}
          ${booking.status === "Approved" ? `<button class="btn bad sm" type="button" onclick="openCancelModal(${booking.booking_id})">Cancel</button>` : ""}
        </div></td>
      </tr>`;
    }).join("");
    const pages = Math.max(1, Math.ceil(result.total / 20));
    const pagination = `<div class="panel-head">
      <span class="muted">Page ${statePage.page} of ${pages}</span>
      <div class="actions">
        <button class="btn ghost sm" type="button" ${statePage.page <= 1 ? "disabled" : ""} onclick="pageBookings('${kind}', ${statePage.page - 1})">Previous</button>
        <button class="btn ghost sm" type="button" ${statePage.page >= pages ? "disabled" : ""} onclick="pageBookings('${kind}', ${statePage.page + 1})">Next</button>
      </div>
    </div>`;
    const content = kind === "my"
      ? `<div class="booking-grid">${rows || `<div class="empty">No bookings match these filters. Your pending, approved, rejected and cancelled history is included here.</div>`}</div>`
      : `<div style="overflow:auto"><table><thead><tr><th>ID</th><th>Requester</th><th>Resource / equipment</th><th>Schedule</th><th>Purpose</th><th>Status</th><th>Actions</th></tr></thead><tbody>${rows || `<tr><td colspan="7" class="empty">No bookings match these filters.</td></tr>`}</tbody></table></div>`;
    $("view").innerHTML = `<div class="panel booking-list-panel">${controls}${content}${pagination}</div>`;
  } catch (err) {
    $("view").innerHTML = `<div class="empty">Failed to load bookings: ${esc(err.message)}</div>`;
  }
}

function changeBookingFilters(kind, resetPage = true) {
  if (resetPage) bookingPageState[kind].page = 1;
  renderBookingPage(kind);
}

function clearBookingFilters(kind) {
  bookingPageState[kind].page = 1;
  renderBookingPage(kind);
}

function pageBookings(kind, page) {
  bookingPageState[kind].page = page;
  renderBookingPage(kind);
}

async function openBookingDetails(bookingId) {
  try {
    const booking = await api.get(`/bookings/${bookingId}`);
    const resources = (booking.resources || []).map(resource => `
      <div class="info-row"><span>${esc(resource.resource_name || "Campus space")}</span><b>${fmt(resource.start_time)} – ${fmtShort(resource.end_time)}</b></div>
    `).join("");
    const equipment = (booking.equipment || []).map(item => `
      <div class="info-row"><span>${esc(item.item_name || "Equipment")} × ${item.requested_quantity}</span><b>${esc(item.category || "")}</b></div>
    `).join("");
    $("modalRoot").innerHTML = `<div class="modal-backdrop" onclick="if(event.target===this)closeModal()"><div class="modal card" style="max-width:580px;margin:auto">
      <div class="modal-head"><h3>Booking BK-${booking.booking_id}</h3><button class="btn ghost sm" onclick="closeModal()">✕</button></div>
      <div class="modal-body"><p><span class="pill ${booking.status === "Approved" ? "ok" : (booking.status === "Pending" ? "warn" : "bad")}">${esc(booking.status)}</span> ${esc(booking.purpose)}</p>
      ${resources}${equipment}${booking.remarks ? `<div class="hint neutral">Decision remarks: ${esc(booking.remarks)}</div>` : ""}
      <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Close</button></div></div></div></div>`;
  } catch (err) {
    toast("Could not load booking details: " + err.message, "err");
  }
}

function openCancelModal(bookingId) {
  const modalHtml = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <div class="modal">
        <div class="modal-head">
          <h2>Cancel Booking BK-${bookingId}</h2>
          <button class="btn icon" type="button" onclick="closeModal()">✕</button>
        </div>
        <div class="modal-body">
          <p class="muted">Are you sure you want to cancel this booking? This will release reserved rooms and equipment immediately.</p>
          <label for="cReason">Reason for cancellation *</label>
          <textarea id="cReason" class="input" rows="3" placeholder="Provide a brief explanation..."></textarea>
          <div class="modal-foot">
            <button class="btn ghost" type="button" onclick="closeModal()">Keep booking</button>
            <button class="btn bad" type="button" onclick="confirmCancelBooking(${bookingId})">Confirm Cancellation</button>
          </div>
        </div>
      </div>
    </div>
  `;
  $("modalRoot").innerHTML = modalHtml;
}

async function confirmCancelBooking(bookingId) {
  const reason = $("cReason").value.trim() || "Cancelled by user";
  try {
    await api.patch(`/bookings/${bookingId}/cancel`, { remarks: reason });
    closeModal();
    toast(`Booking BK-${bookingId} cancelled.`, "ok");
    if (state.view === "mybookings") renderMyBookings();
    else if (state.view === "allbookings") renderAllBookings();
  } catch (err) {
    toast("Cancellation failed: " + err.message, "err");
  }
}

async function openBookingHistory(bookingId) {
  try {
    const [audits, b] = await Promise.all([
      api.get("/reports/audit", { q: `BK-${bookingId}` }),
      api.get(`/bookings/${bookingId}`)
    ]);

    let timelineHtml = "";
    if (audits.length) {
      timelineHtml = audits.map(a => `
        <div class="timeline-event">
          <div class="timeline-dot ${a.action === 'Approved' ? 'dot-ok' : (a.action === 'Rejected' || a.action === 'Cancelled' ? 'dot-bad' : 'dot-info')}"></div>
          <div class="timeline-content">
            <div class="timeline-head">
              <span class="timeline-action">${esc(a.action)}</span>
              <span class="timeline-time">${fmt(a.changed_at)}</span>
            </div>
            <div class="timeline-actor">By <b>${esc(a.changed_by)}</b> (${esc(a.changed_by_role)})</div>
            ${a.remarks ? `<div class="timeline-remarks">${esc(a.remarks)}</div>` : ''}
          </div>
        </div>
      `).join("");
    } else {
      timelineHtml = `<div class="hint neutral">No audit entries recorded for this booking yet.</div>`;
    }

    const modalHtml = `
      <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
        <div class="modal wide">
          <div class="modal-head">
            <div>
              <h2>Booking BK-${bookingId} — Audit Trail</h2>
              <div class="muted">${esc(b.purpose)}</div>
            </div>
            <button class="btn icon" type="button" onclick="closeModal()">✕</button>
          </div>
          <div class="modal-body">
            <div class="history-details" style="margin-bottom:18px">
              <div>
                <div class="history-label">Requester</div>
                <div class="history-value">${esc(b.user_name)} (${esc(b.user_email)})</div>
              </div>
              <div>
                <div class="history-label">Current Status</div>
                <div class="history-value"><span class="pill ${b.status==='Approved'?'ok':(b.status==='Pending'?'warn':'bad')}">${esc(b.status)}</span></div>
              </div>
              <div class="history-field full">
                <div class="history-label">Reserved Resource(s)</div>
                <div class="history-value">${b.resources.map(r => `${esc(r.resource_name)} (${fmtShort(r.start_time)} – ${fmtShort(r.end_time)})`).join("<br>")}</div>
              </div>
            </div>
            <h3 style="font-size:14px;margin-bottom:14px">Lifecycle Timeline</h3>
            <div class="timeline">${timelineHtml}</div>
            <div class="modal-foot">
              <button class="btn ghost" type="button" onclick="closeModal()">Close</button>
            </div>
          </div>
        </div>
      </div>
    `;
    $("modalRoot").innerHTML = modalHtml;
  } catch (err) {
    toast("Failed to load audit history: " + err.message, "err");
  }
}

// Global window registrations
window.renderMyBookings = renderMyBookings;
window.renderAllBookings = renderAllBookings;
window.renderBookingPage = renderBookingPage;
window.changeBookingFilters = changeBookingFilters;
window.pageBookings = pageBookings;
window.openBookingDetails = openBookingDetails;
window.openBookingModal = openBookingModal;
window.openBookingHistory = openBookingHistory;
window.openCancelModal = openCancelModal;
window.confirmCancelBooking = confirmCancelBooking;
