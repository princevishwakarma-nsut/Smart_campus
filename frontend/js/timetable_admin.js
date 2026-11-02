/* =========================================================
   Smart Campus — Admin Faculty Timetable Assignment Module
   ========================================================= */

let ttEntriesCache = [];
let facultyUsersCache = [];

async function renderTimetableAssignments() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading academic timetable and faculty assignments...</div>`;

  try {
    const [entries, facultyUsers] = await Promise.all([
      api.get("/timetable/assignments"),
      api.get("/timetable/faculty-users")
    ]);

    ttEntriesCache = entries || [];
    facultyUsersCache = facultyUsers || [];

    renderTimetableAssignmentsView();
  } catch (err) {
    host.innerHTML = `<div class="hint error">Failed to load timetable assignments: ${esc(err.message)}</div>`;
  }
}

function renderTimetableAssignmentsView(filterDept = "All", unassignedOnly = false, searchQ = "") {
  const host = $("view");

  const depts = ["All", ...new Set(ttEntriesCache.map(e => e.department_name).filter(Boolean))];

  const filtered = ttEntriesCache.filter(e => {
    if (filterDept !== "All" && e.department_name !== filterDept) return false;
    if (unassignedOnly && e.assigned_faculty && e.assigned_faculty.length > 0) return false;
    if (searchQ) {
      const q = searchQ.toLowerCase();
      const matchSub = e.subject_name && e.subject_name.toLowerCase().includes(q);
      const matchSec = e.section && e.section.toLowerCase().includes(q);
      const matchRoom = e.resource_name && e.resource_name.toLowerCase().includes(q);
      if (!matchSub && !matchSec && !matchRoom) return false;
    }
    return true;
  });

  const rows = filtered.map(e => {
    const facPills = (e.assigned_faculty && e.assigned_faculty.length)
      ? e.assigned_faculty.map(f => `
          <span class="pill info" style="display:inline-flex; align-items:center; gap:4px; margin:2px;">
            ${esc(f.name)}
            <button type="button" style="background:none; border:none; cursor:pointer; color:inherit; font-size:12px; padding:0 2px;"
                    title="Remove assignment" onclick="removeFacultyAssignment(${e.timetable_id}, ${f.user_id}, '${esc(f.name)}')">✕</button>
          </span>
        `).join('')
      : `<span class="pill warn" style="font-size:11px;">Unassigned</span>`;

    return `
      <tr>
        <td><b>${esc(e.department_name)}</b> - ${esc(e.section)}</td>
        <td><b>${esc(e.subject_name)}</b> <span class="muted" style="font-size:11px;">(${esc(e.class_type)})</span></td>
        <td>${esc(e.resource_name || 'Room ' + e.resource_id)}</td>
        <td>${esc(e.day_of_week)}</td>
        <td style="white-space:nowrap;">${esc(e.start_time.substring(0,5))} – ${esc(e.end_time.substring(0,5))}</td>
        <td>${facPills}</td>
        <td style="white-space:nowrap; text-align:right;">
          <button type="button" class="btn primary sm" onclick="openAssignFacultyModal(${e.timetable_id}, '${esc(e.subject_name)}', '${esc(e.section)}')">+ Assign</button>
        </td>
      </tr>
    `;
  }).join('');

  host.innerHTML = `
    <div style="max-width:1100px; margin:0 auto;">
      <div class="panel pad" style="margin-bottom:16px;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
          <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
            <div>
              <label style="font-size:12px; font-weight:600; display:block; margin-bottom:4px;">Department</label>
              <select id="ttDeptFilter" class="input" style="width:140px;" onchange="applyTtFilters()">
                ${depts.map(d => `<option value="${esc(d)}" ${d===filterDept?'selected':''}>${esc(d)}</option>`).join('')}
              </select>
            </div>
            <div>
              <label style="font-size:12px; font-weight:600; display:block; margin-bottom:4px;">Search Subject / Section / Room</label>
              <input id="ttSearchQ" type="text" class="input" placeholder="e.g. Algorithms or CSE-1" value="${esc(searchQ)}" style="width:220px;" oninput="applyTtFilters()">
            </div>
            <div style="margin-top:18px;">
              <label style="font-size:13px; cursor:pointer; display:flex; align-items:center; gap:6px;">
                <input id="ttUnassignedOnly" type="checkbox" ${unassignedOnly?'checked':''} onchange="applyTtFilters()">
                <span>Unassigned only</span>
              </label>
            </div>
          </div>
          <div class="muted" style="font-size:13px; align-self:flex-end;">
            Showing <b>${filtered.length}</b> of ${ttEntriesCache.length} timetable entries
          </div>
        </div>
      </div>

      <div class="panel pad" style="padding:0; overflow:hidden;">
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Dept &amp; Section</th>
                <th>Subject &amp; Type</th>
                <th>Room</th>
                <th>Day</th>
                <th>Time</th>
                <th>Assigned Faculty</th>
                <th style="text-align:right;">Action</th>
              </tr>
            </thead>
            <tbody>
              ${filtered.length ? rows : `<tr><td colspan="7" class="empty">No matching timetable entries found.</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;
}

function applyTtFilters() {
  const dept = $("ttDeptFilter") ? $("ttDeptFilter").value : "All";
  const searchQ = $("ttSearchQ") ? $("ttSearchQ").value.trim() : "";
  const unassigned = $("ttUnassignedOnly") ? $("ttUnassignedOnly").checked : false;
  renderTimetableAssignmentsView(dept, unassigned, searchQ);
}

function openAssignFacultyModal(timetableId, subjectName, section) {
  const modalRoot = $("modalRoot");
  if (!modalRoot) return;

  const facOptions = facultyUsersCache.map(f => `
    <option value="${f.user_id}">${esc(f.name)} (${esc(f.department_name || 'Faculty')}) - ${esc(f.email)}</option>
  `).join('');

  modalRoot.innerHTML = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <div class="modal card" style="max-width:480px; margin:auto;">
        <div class="modal-head" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
          <div>
            <h3>Assign Faculty</h3>
            <p class="sub" style="margin:0;">${esc(subjectName)} (${esc(section)})</p>
          </div>
          <button class="btn ghost sm" type="button" onclick="closeModal()">✕</button>
        </div>
        <div class="modal-body">
          <div class="field" style="margin-bottom:16px;">
            <label for="assignFacultySelect" style="display:block; font-weight:600; margin-bottom:6px;">Select Faculty Member</label>
            <select id="assignFacultySelect" class="input" style="width:100%;">
              ${facOptions.length ? facOptions : `<option value="">No active faculty accounts available</option>`}
            </select>
          </div>
        </div>
        <div class="modal-foot" style="display:flex; justify-content:flex-end; gap:8px;">
          <button class="btn ghost sm" type="button" onclick="closeModal()">Cancel</button>
          <button class="btn primary sm" type="button" onclick="submitFacultyAssignment(${timetableId})" ${!facOptions.length?'disabled':''}>Assign</button>
        </div>
      </div>
    </div>
  `;
}

async function submitFacultyAssignment(timetableId) {
  const select = $("assignFacultySelect");
  if (!select || !select.value) {
    toast("Please select a faculty member.", "err");
    return;
  }

  const facultyUserId = parseInt(select.value, 10);
  try {
    await api.post(`/timetable/${timetableId}/assign`, { faculty_user_id: facultyUserId });
    toast("Faculty successfully assigned to timetable slot!", "ok");
    closeModal();
    renderTimetableAssignments();
  } catch (err) {
    toast("Assignment failed: " + err.message, "err");
  }
}

async function removeFacultyAssignment(timetableId, facultyUserId, facultyName) {
  if (!confirm(`Are you sure you want to remove ${facultyName} from this timetable slot?`)) return;

  try {
    await api.delete(`/timetable/${timetableId}/assignments/${facultyUserId}`);
    toast(`Assignment removed for ${facultyName}`, "ok");
    renderTimetableAssignments();
  } catch (err) {
    toast("Failed to remove assignment: " + err.message, "err");
  }
}

window.renderTimetableAssignments = renderTimetableAssignments;
window.applyTtFilters = applyTtFilters;
window.openAssignFacultyModal = openAssignFacultyModal;
window.submitFacultyAssignment = submitFacultyAssignment;
window.removeFacultyAssignment = removeFacultyAssignment;
