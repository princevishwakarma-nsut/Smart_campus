/* =========================================================
   Smart Campus — Blackout & Maintenance Windows Module (Admin/Staff)
   ========================================================= */

let blackoutsCache = [];
let blackoutResourcesCache = [];

async function renderBlackouts() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading blackout periods...</div>`;

  $("topActions").innerHTML = `
    <button class="btn primary sm" type="button" onclick="openCreateBlackoutModal()">+ Add Blackout Window</button>
  `;

  try {
    const [blackouts, resources] = await Promise.all([
      api.get("/blackouts"),
      api.get("/resources")
    ]);
    blackoutsCache = blackouts || [];
    blackoutResourcesCache = resources || [];
    renderBlackoutsTable();
  } catch (err) {
    host.innerHTML = `<div class="hint error">Failed to load blackouts: ${esc(err.message)}</div>`;
  }
}

function renderBlackoutsTable(filterRes = "All") {
  const host = $("view");
  const filtered = blackoutsCache.filter(b => {
    if (filterRes !== "All" && String(b.resource_id) !== String(filterRes)) return false;
    return true;
  });

  const resOpts = blackoutResourcesCache.map(r =>
    `<option value="${r.resource_id}" ${String(filterRes) === String(r.resource_id) ? 'selected' : ''}>${esc(r.resource_name)}</option>`
  ).join("");

  host.innerHTML = `
    <div class="card" style="margin-bottom:16px;">
      <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center;">
        <label class="muted" style="font-size:13px;">Filter by Resource:</label>
        <select id="blackoutResFilter" class="input" style="width:240px;" onchange="renderBlackoutsTable(this.value)">
          <option value="All">All Resources</option>
          ${resOpts}
        </select>
        <span class="muted" style="font-size:13px;">${filtered.length} blackout window(s) recorded</span>
      </div>
    </div>

    <div class="card">
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Resource</th>
              <th>Reason</th>
              <th>Window Start</th>
              <th>Window End</th>
              <th>Source</th>
              <th>Created By</th>
              <th style="text-align:right;">Actions</th>
            </tr>
          </thead>
          <tbody>
            ${filtered.length === 0 ? `<tr><td colspan="7" class="empty">No blackout periods currently scheduled.</td></tr>` : ''}
            ${filtered.map(b => {
              const isMaint = b.maintenance_id !== null;
              return `
                <tr>
                  <td><b>${esc(b.resource_name)}</b></td>
                  <td>${esc(b.reason)}</td>
                  <td>${fmt(b.start_datetime)}</td>
                  <td>${fmt(b.end_datetime)}</td>
                  <td>
                    <span class="pill ${isMaint ? 'warn' : 'info'}">
                      ${isMaint ? 'Maintenance #' + b.maintenance_id : 'Campus Event / Holiday'}
                    </span>
                  </td>
                  <td>${esc(b.creator_name || 'System')}</td>
                  <td style="text-align:right;">
                    <button class="btn danger sm" type="button" onclick="deleteBlackoutRecord(${b.blackout_id})">Delete</button>
                  </td>
                </tr>
              `;
            }).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function openCreateBlackoutModal() {
  const root = $("modalRoot");
  const resOpts = blackoutResourcesCache.map(r =>
    `<option value="${r.resource_id}">${esc(r.resource_name)} (${esc(r.category_name)})</option>`
  ).join("");

  const now = new Date();
  const later = new Date(now.getTime() + 4 * 3600 * 1000);

  root.innerHTML = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <div class="modal card" style="max-width:520px;margin:auto;">
        <h3>Schedule Blackout Window</h3>
        <p class="sub">Block reservations for university holidays, VIP visits, or renovations.</p>

        <div class="field">
          <label>Resource to Block</label>
          <select id="newBlackoutRes" class="input">
            ${resOpts}
          </select>
        </div>

        <div class="field">
          <label>Start Date &amp; Time</label>
          <input id="newBlackoutStart" class="input" type="datetime-local" value="${toLocalInput(now)}">
        </div>

        <div class="field">
          <label>End Date &amp; Time</label>
          <input id="newBlackoutEnd" class="input" type="datetime-local" value="${toLocalInput(later)}">
        </div>

        <div class="field">
          <label>Reason / Official Event</label>
          <textarea id="newBlackoutReason" class="input" rows="3" placeholder="e.g. Annual Convocation Rehearsal, Deep Cleaning, Campus Holiday"></textarea>
        </div>

        <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:20px;">
          <button class="btn ghost sm" type="button" onclick="closeModal()">Cancel</button>
          <button class="btn primary sm" type="button" onclick="submitCreateBlackout()">Save Blackout</button>
        </div>
      </div>
    </div>
  `;
}

async function submitCreateBlackout() {
  const resId = parseInt($("newBlackoutRes").value, 10);
  const start = $("newBlackoutStart").value;
  const end = $("newBlackoutEnd").value;
  const reason = $("newBlackoutReason").value.trim();

  if (!resId || !start || !end || !reason) {
    toast("Please specify the resource, dates and reason.", "err");
    return;
  }
  if (new Date(start) >= new Date(end)) {
    toast("Start time must be before end time.", "err");
    return;
  }

  try {
    await api.post("/blackouts", {
      resource_id: resId,
      start_datetime: start,
      end_datetime: end,
      reason: reason
    });
    toast("Blackout window created.", "ok");
    closeModal();
    renderBlackouts();
  } catch (err) {
    toast(err.message || "Failed to create blackout window.", "err");
  }
}

async function deleteBlackoutRecord(blackoutId) {
  if (!confirm("Are you sure you want to remove this blackout window? Available slots will be opened.")) return;
  try {
    await api.delete(`/blackouts/${blackoutId}`);
    toast("Blackout period deleted.", "ok");
    renderBlackouts();
  } catch (err) {
    toast(err.message || "Failed to delete blackout.", "err");
  }
}

// Global window registrations
window.renderBlackouts = renderBlackouts;
window.renderBlackoutsTable = renderBlackoutsTable;
window.openCreateBlackoutModal = openCreateBlackoutModal;
window.submitCreateBlackout = submitCreateBlackout;
window.deleteBlackoutRecord = deleteBlackoutRecord;
