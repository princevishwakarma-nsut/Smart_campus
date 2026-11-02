/* =========================================================
   Smart Campus — User Management Module (Admin Only)
   ========================================================= */

let usersCache = [];
let userDeptsCache = [];

async function renderUsers() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading campus directory...</div>`;

  $("topActions").innerHTML = `
    <button class="btn ghost sm" type="button" onclick="openFacultyRequestsModal()">Faculty Requests</button>
    <button class="btn primary sm" type="button" onclick="openCreateUserModal()">+ Add User</button>
  `;

  try {
    const [users, depts] = await Promise.all([
      api.get("/users"),
      api.get("/departments").catch(() => [])
    ]);
    usersCache = users || [];
    userDeptsCache = Array.isArray(depts) ? depts : [];
    renderUsersTable();
  } catch (err) {
    host.innerHTML = `<div class="hint error">Failed to load users: ${esc(err.message)}</div>`;
  }
}

function renderUsersTable(filterRole = "All", searchQ = "") {
  const host = $("view");
  const filtered = usersCache.filter(u => {
    if (filterRole !== "All" && u.role !== filterRole) return false;
    if (searchQ) {
      const q = searchQ.toLowerCase();
      const uName = u.name || u.full_name || "";
      const matchName = uName.toLowerCase().includes(q);
      const matchEmail = u.email && u.email.toLowerCase().includes(q);
      const matchDept = u.department_name && u.department_name.toLowerCase().includes(q);
      if (!matchName && !matchEmail && !matchDept) return false;
    }
    return true;
  });

  host.innerHTML = `
    <div class="card" style="margin-bottom:16px;">
      <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center;">
        <input id="userSearchInput" class="input" style="flex:1;min-width:200px;" type="text"
          placeholder="Search by name, email or department..." value="${esc(searchQ)}"
          oninput="onUserFilterChange()">
        <select id="userRoleFilter" class="input" style="width:160px;" onchange="onUserFilterChange()">
          <option value="All" ${filterRole === 'All' ? 'selected' : ''}>All Roles</option>
          <option value="Student" ${filterRole === 'Student' ? 'selected' : ''}>Student</option>
          <option value="Faculty" ${filterRole === 'Faculty' ? 'selected' : ''}>Faculty</option>
          <option value="Staff" ${filterRole === 'Staff' ? 'selected' : ''}>Staff</option>
          <option value="Admin" ${filterRole === 'Admin' ? 'selected' : ''}>Admin</option>
        </select>
        <span class="muted" style="font-size:13px;">Showing ${filtered.length} of ${usersCache.length} users</span>
      </div>
    </div>

    <div class="card">
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>User</th>
              <th>Role</th>
              <th>Department</th>
              <th>Contact</th>
              <th>Status</th>
              <th style="text-align:right;">Actions</th>
            </tr>
          </thead>
          <tbody>
            ${filtered.length === 0 ? `<tr><td colspan="6" class="empty">No matching users found.</td></tr>` : ''}
            ${filtered.map(u => `
              <tr>
                <td>
                  <b>${esc(u.name || u.full_name)}</b>
                  <div class="muted" style="font-size:12px;">${esc(u.email)}</div>
                </td>
                <td><span class="pill ${u.role === 'Admin' ? 'warn' : u.role === 'Faculty' ? 'info' : 'neutral'}">${esc(u.role)}</span></td>
                <td>${esc(u.department_name || '—')}</td>
                <td>${esc(u.phone_no || u.phone_number || '—')}</td>
                <td>
                  <span class="pill ${u.is_active ? 'ok' : 'err'}">${u.is_active ? 'Active' : 'Inactive'}</span>
                </td>
                <td style="text-align:right;">
                  <button class="btn ghost sm" type="button" onclick="openEditUserModal(${u.user_id})">Edit</button>
                  <button class="btn ${u.is_active ? 'danger' : 'ok'} sm" type="button" onclick="toggleUserStatus(${u.user_id}, ${u.is_active})">
                    ${u.is_active ? 'Deactivate' : 'Activate'}
                  </button>
                </td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function onUserFilterChange() {
  const q = $("userSearchInput") ? $("userSearchInput").value : "";
  const role = $("userRoleFilter") ? $("userRoleFilter").value : "All";
  renderUsersTable(role, q);
}

function openCreateUserModal() {
  const root = $("modalRoot");
  const deptOpts = userDeptsCache.map(d => `<option value="${d.department_id}">${esc(d.name || d.department_name)}</option>`).join("");

  root.innerHTML = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <div class="modal card" style="max-width:520px;margin:auto;">
        <h3>Add Campus User</h3>
        <p class="sub">Provision authorized faculty, staff or administrator account.</p>

        <div class="field">
          <label>Full Name</label>
          <input id="newUserName" class="input" type="text" placeholder="Dr. Jane Smith">
        </div>

        <div class="field">
          <label>Email Address</label>
          <input id="newUserEmail" class="input" type="email" placeholder="jane.smith@campus.edu">
        </div>

        <div class="field">
          <label>Role</label>
          <select id="newUserRole" class="input">
            <option value="Faculty">Faculty</option>
            <option value="Staff">Staff</option>
            <option value="Admin">Admin</option>
            <option value="Student">Student</option>
          </select>
        </div>

        <div class="field">
          <label>Department</label>
          <select id="newUserDept" class="input">
            <option value="">-- No Department --</option>
            ${deptOpts}
          </select>
        </div>

        <div class="field">
          <label>Phone Number (Optional)</label>
          <input id="newUserPhone" class="input" type="tel" placeholder="+91 9876543210">
        </div>

        <div class="field">
          <label>Initial Password (min 8 chars)</label>
          <input id="newUserPass" class="input" type="password" placeholder="••••••••">
        </div>

        <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:20px;">
          <button class="btn ghost sm" type="button" onclick="closeModal()">Cancel</button>
          <button class="btn primary sm" type="button" onclick="submitCreateUser()">Create User</button>
        </div>
      </div>
    </div>
  `;
}

async function submitCreateUser() {
  const name = $("newUserName").value.trim();
  const email = $("newUserEmail").value.trim();
  const role = $("newUserRole").value;
  const deptId = $("newUserDept").value ? parseInt($("newUserDept").value, 10) : null;
  const phone = $("newUserPhone").value.trim();
  const pass = $("newUserPass").value;

  if (!name || !email || !pass) {
    toast("Name, email and password are required.", "err");
    return;
  }
  if (pass.length < 8) {
    toast("Password must be at least 8 characters.", "err");
    return;
  }

  try {
    await api.post("/users", {
      name: name,
      email: email,
      role: role,
      department_id: deptId,
      phone_no: phone || null,
      password: pass
    });
    toast("User created successfully.", "ok");
    closeModal();
    renderUsers();
  } catch (err) {
    toast(err.message || "Failed to create user.", "err");
  }
}

function openEditUserModal(userId) {
  const u = usersCache.find(x => x.user_id === userId);
  if (!u) return;

  const root = $("modalRoot");
  const deptOpts = userDeptsCache.map(d =>
    `<option value="${d.department_id}" ${u.department_id === d.department_id ? 'selected' : ''}>${esc(d.name || d.department_name)}</option>`
  ).join("");

  root.innerHTML = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <div class="modal card" style="max-width:520px;margin:auto;">
        <h3>Edit User: ${esc(u.name || u.full_name)}</h3>
        <p class="sub">${esc(u.email)}</p>

        <div class="field">
          <label>Full Name</label>
          <input id="editUserName" class="input" type="text" value="${esc(u.name || u.full_name)}">
        </div>

        <div class="field">
          <label>Role</label>
          <select id="editUserRole" class="input">
            <option value="Student" ${u.role === 'Student' ? 'selected' : ''}>Student</option>
            <option value="Faculty" ${u.role === 'Faculty' ? 'selected' : ''}>Faculty</option>
            <option value="Staff" ${u.role === 'Staff' ? 'selected' : ''}>Staff</option>
            <option value="Admin" ${u.role === 'Admin' ? 'selected' : ''}>Admin</option>
          </select>
        </div>

        <div class="field">
          <label>Department</label>
          <select id="editUserDept" class="input">
            <option value="">-- No Department --</option>
            ${deptOpts}
          </select>
        </div>

        <div class="field">
          <label>Phone Number</label>
          <input id="editUserPhone" class="input" type="tel" value="${esc(u.phone_no || u.phone_number || '')}">
        </div>

        <div class="field">
          <label>Reset Password (leave blank to keep current)</label>
          <input id="editUserPass" class="input" type="password" placeholder="New password">
        </div>

        <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:20px;">
          <button class="btn ghost sm" type="button" onclick="closeModal()">Cancel</button>
          <button class="btn primary sm" type="button" onclick="submitEditUser(${userId})">Save Changes</button>
        </div>
      </div>
    </div>
  `;
}

async function submitEditUser(userId) {
  const name = $("editUserName").value.trim();
  const role = $("editUserRole").value;
  const deptId = $("editUserDept").value ? parseInt($("editUserDept").value, 10) : null;
  const phone = $("editUserPhone").value.trim();
  const pass = $("editUserPass").value;

  if (!name) {
    toast("Full name is required.", "err");
    return;
  }

  const payload = {
    name: name,
    role: role,
    department_id: deptId,
    phone_no: phone || null
  };

  if (pass && pass.length < 8) {
    toast("Password must be at least 8 characters.", "err");
    return;
  }

  try {
    await api.put(`/users/${userId}`, payload);
    if (pass) {
      await api.post(`/users/${userId}/reset-password`, { new_password: pass });
      toast("User details and password reset successfully.", "ok");
    } else {
      toast("User updated successfully.", "ok");
    }
    closeModal();
    renderUsers();
  } catch (err) {
    toast(err.message || "Failed to update user.", "err");
  }
}

async function toggleUserStatus(userId, currentStatus) {
  const newStatus = !currentStatus;
  const action = newStatus ? "activate" : "deactivate";
  if (!confirm(`Are you sure you want to ${action} this user?`)) return;

  try {
    await api.patch(`/users/${userId}/status`, { is_active: newStatus });
    toast(`User ${action}d successfully.`, "ok");
    renderUsers();
  } catch (err) {
    toast(err.message || `Failed to ${action} user.`, "err");
  }
}

async function openFacultyRequestsModal() {
  try {
    const list = await api.get("/users/faculty-requests");

    let rowsHtml = "";
    if (list.length) {
      rowsHtml = list.map(r => `
        <tr>
          <td>
            <div class="cell-strong">${esc(r.name)}</div>
            <div class="muted" style="font-size:11.5px;">${esc(r.email)}</div>
          </td>
          <td><b>${esc(r.employee_id)}</b><div class="muted" style="font-size:11px;">${esc(r.designation || 'Faculty')}</div></td>
          <td>${esc(r.department_name || 'General')}</td>
          <td>
            <span class="pill ${r.status === 'Approved' ? 'ok' : (r.status === 'Pending' ? 'warn' : 'bad')}">
              ${esc(r.status)}
            </span>
            ${r.rejection_reason ? `<div class="muted" style="font-size:10.5px;max-width:140px;">${esc(r.rejection_reason)}</div>` : ''}
          </td>
          <td>
            ${r.status === 'Pending' ? `
              <div class="actions" style="display:flex;gap:4px;">
                <button class="btn ok sm" type="button" onclick="approveFacultyRequest(${r.request_id}, '${esc(r.name)}')">Approve</button>
                <button class="btn bad sm" type="button" onclick="rejectFacultyRequest(${r.request_id}, '${esc(r.name)}')">Reject</button>
              </div>
            ` : `<span class="muted" style="font-size:12px;">Reviewed</span>`}
          </td>
        </tr>
      `).join("");
    } else {
      rowsHtml = `<tr><td colspan="5" class="empty">No faculty registration requests found.</td></tr>`;
    }

    const modalHtml = `
      <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
        <div class="modal wide card" style="max-width:820px;margin:auto;">
          <div class="modal-head" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
            <div>
              <h3>Faculty Registration Requests</h3>
              <p class="sub" style="margin:0;">Review self-registered faculty requests and verify staff identity before account activation.</p>
            </div>
            <button class="btn ghost sm" type="button" onclick="closeModal()">✕</button>
          </div>
          <div class="modal-body">
            <div class="table-wrap">
              <table class="table">
                <thead>
                  <tr>
                    <th>Faculty Member</th>
                    <th>Staff / Employee ID</th>
                    <th>Department</th>
                    <th>Status</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>${rowsHtml}</tbody>
              </table>
            </div>
            <div class="modal-foot" style="margin-top:16px;text-align:right;">
              <button class="btn ghost sm" type="button" onclick="closeModal()">Close</button>
            </div>
          </div>
        </div>
      </div>
    `;
    $("modalRoot").innerHTML = modalHtml;
  } catch (err) {
    toast("Failed to load faculty requests: " + err.message, "err");
  }
}

async function approveFacultyRequest(requestId, name) {
  if (!confirm(`Approve faculty account request for "${name}"?`)) return;
  try {
    const res = await api.post(`/users/faculty-requests/${requestId}/approve`);
    toast(res.message || "Faculty request approved.", "ok");
    openFacultyRequestsModal();
    renderUsers();
  } catch (err) {
    toast(err.message || "Failed to approve faculty request.", "err");
  }
}

async function rejectFacultyRequest(requestId, name) {
  const reason = prompt(`Reason for rejecting faculty request for "${name}":`, "Employee credentials could not be verified.");
  if (reason === null) return;

  try {
    const res = await api.post(`/users/faculty-requests/${requestId}/reject`, { reason });
    toast(res.message || "Faculty request rejected.", "ok");
    openFacultyRequestsModal();
  } catch (err) {
    toast(err.message || "Failed to reject faculty request.", "err");
  }
}

// Global window registrations
window.renderUsers = renderUsers;
window.renderUsersTable = renderUsersTable;
window.onUserFilterChange = onUserFilterChange;
window.openCreateUserModal = openCreateUserModal;
window.submitCreateUser = submitCreateUser;
window.openEditUserModal = openEditUserModal;
window.submitEditUser = submitEditUser;
window.openFacultyRequestsModal = openFacultyRequestsModal;
window.approveFacultyRequest = approveFacultyRequest;
window.rejectFacultyRequest = rejectFacultyRequest;
window.toggleUserStatus = toggleUserStatus;
