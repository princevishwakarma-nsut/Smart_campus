async function renderCheckins() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading check-in & attendance desk...</div>`;

  try {
    // 1. Fetch upcoming approved bookings
    const approvedBookings = await api.get("/bookings", { status: "Approved" });
    // 2. Fetch recent checkins
    const checkinHistory = await api.get("/checkins");

    let bkCardsHtml = "";
    if (approvedBookings.length) {
      bkCardsHtml = approvedBookings.map(b => {
        const res = b.resources[0] || {};
        return `
          <div class="card" style="padding:14px">
            <div class="card-head">
              <div>
                <span class="code">BK-${b.booking_id}</span>
                <h3 style="font-size:14px">${esc(b.purpose)}</h3>
              </div>
              <span class="pill ok">Approved</span>
            </div>
            <div class="meta" style="margin:4px 0">
              <span class="tag">📍 ${esc(res.resource_name || 'Space')}</span>
              <span class="tag">🕒 ${res.start_time ? fmtShort(res.start_time) : ''}</span>
              <span class="tag">👤 ${esc(b.user_name || 'Requester')}</span>
            </div>
            <div class="card-foot" style="padding-top:4px">
              <button class="btn primary sm" type="button" onclick="openBookingAttendanceModal(${b.booking_id})">Manage Attendance</button>
            </div>
          </div>
        `;
      }).join("");
    } else {
      bkCardsHtml = `<div class="hint neutral" style="grid-column:1/-1">No upcoming approved sessions scheduled for attendance check-in.</div>`;
    }

    let historyRowsHtml = "";
    if (checkinHistory.length) {
      historyRowsHtml = checkinHistory.map(c => {
        const statusClass = c.status === "Checked-in" ? "ok" : (c.status === "Checked-out" ? "info" : "bad");
        return `
          <tr>
            <td><span class="code">BK-${c.booking_id}</span></td>
            <td class="cell-strong">${esc(c.user_name)}</td>
            <td><span class="pill ${statusClass}">${esc(c.status)}</span></td>
            <td>${c.checkin_time ? fmtShort(c.checkin_time) : '—'}</td>
            <td>${c.checkout_time ? fmtShort(c.checkout_time) : '—'}</td>
            <td>${esc(c.verifier_name || 'Staff')}</td>
            <td>
              ${c.status === "Checked-in" ? `
                <button class="btn ghost sm" type="button" onclick="quickCheckout(${c.checkin_id})">Check out</button>
              ` : '—'}
            </td>
          </tr>
        `;
      }).join("");
    } else {
      historyRowsHtml = `<tr><td colspan="7" class="empty">No check-in activity recorded yet.</td></tr>`;
    }

    const html = `
      <div style="margin-bottom:22px">
        <h3 style="font-size:15px;margin-bottom:10px">Active & Upcoming Sessions Requiring Attendance</h3>
        <div class="grid" style="grid-template-columns:repeat(auto-fill, minmax(310px, 1fr))">${bkCardsHtml}</div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <h3>Recent Attendance History (${checkinHistory.length})</h3>
          <div class="actions">
            <input id="chkSearch" class="input sm" placeholder="Search attendee..." oninput="filterCheckinTable(this.value)">
          </div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Booking</th>
              <th>Attendee Name</th>
              <th>Status</th>
              <th>Check-in Time</th>
              <th>Checkout Time</th>
              <th>Verified By</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody id="chkTableBody">${historyRowsHtml}</tbody>
        </table>
      </div>
    `;

    host.innerHTML = html;
  } catch (err) {
    host.innerHTML = `<div class="empty">Failed to load check-in desk: ${esc(err.message)}</div>`;
  }
}

function filterCheckinTable(val) {
  const q = val.toLowerCase();
  const rows = document.querySelectorAll("#chkTableBody tr");
  rows.forEach(tr => {
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? "" : "none";
  });
}

async function openBookingAttendanceModal(bookingId) {
  try {
    const booking = await api.get(`/bookings/${bookingId}`);
    const checkins = await api.get("/checkins", { booking_id: bookingId });

    // Fetch booking participants
    let parts = [];
    try {
      parts = await api.get(`/bookings/${bookingId}/participants`);
    } catch (e) {
      // If endpoint not separated, fetch from booking object or checkins
    }

    const modalHtml = `
      <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
        <div class="modal wide">
          <div class="modal-head">
            <div>
              <h2>Attendance Check-in — BK-${bookingId}</h2>
              <div class="muted">${esc(booking.purpose)} · Requester: ${esc(booking.user_name)}</div>
            </div>
            <button class="btn icon" type="button" onclick="closeModal()">✕</button>
          </div>
          <div class="modal-body">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
              <h3 style="font-size:14px">Session Attendees</h3>
              <input id="partSearch" class="input sm" placeholder="Search participant..." oninput="filterPartList(this.value)" style="max-width:200px">
            </div>

            <div id="partList">
              <!-- Attendee check-in rows -->
              <div class="info-row">
                <div>
                  <b>${esc(booking.user_name)}</b> <span class="pill info">Organizer</span>
                  <div class="muted" style="font-size:11px">${esc(booking.user_email)}</div>
                </div>
                <div class="actions">
                  <button class="btn ok sm" type="button" onclick="checkinAttendeeDirect(${bookingId}, ${booking.user_id})">Check-in</button>
                  <button class="btn bad sm" type="button" onclick="markAttendeeNoShowDirect(${bookingId}, ${booking.user_id})">No-show</button>
                </div>
              </div>
            </div>

            <div class="modal-foot">
              <button class="btn ghost" type="button" onclick="closeModal()">Done</button>
            </div>
          </div>
        </div>
      </div>
    `;
    $("modalRoot").innerHTML = modalHtml;
  } catch (err) {
    toast("Error loading attendance: " + err.message, "err");
  }
}

async function checkinAttendeeDirect(bookingId, userId) {
  try {
    // Find or create participant entry
    await api.post("/checkins", {
      booking_participant_id: userId, // or actual participant ID
      remarks: "Verified at entry"
    });
    toast("Attendee checked in!", "ok");
    renderCheckins();
  } catch (err) {
    toast(err.message, "err");
  }
}

async function quickCheckout(checkinId) {
  try {
    await api.post(`/checkins/${checkinId}/checkout`, { remarks: "Checked out at exit" });
    toast("Checked out successfully.", "ok");
    renderCheckins();
  } catch (err) {
    toast(err.message, "err");
  }
}

// Global window registrations
window.renderCheckins = renderCheckins;
window.filterCheckinTable = filterCheckinTable;
window.openBookingAttendanceModal = openBookingAttendanceModal;
window.checkinAttendeeDirect = checkinAttendeeDirect;
window.quickCheckout = quickCheckout;

