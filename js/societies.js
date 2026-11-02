/* =========================================================
   Smart Campus — Societies & Club Management Module
   ========================================================= */

async function openSocietiesModal() {
  try {
    const list = await api.get("/societies");

    let rowsHtml = "";
    if (list.length) {
      rowsHtml = list.map(s => `
        <tr>
          <td class="cell-strong"><b>${esc(s.club_name)}</b></td>
          <td>${esc(s.department_name || 'General')}</td>
          <td>${esc(s.faculty_coordinator_name || '—')}</td>
          <td><span class="pill info">${s.members_count} members</span></td>
          <td>
            <span class="pill ${s.status === 'Approved' ? 'ok' : (s.status === 'Pending' ? 'warn' : 'bad')}">
              ${esc(s.status || (s.is_active ? 'Approved' : 'Pending'))}
            </span>
            ${s.rejection_reason ? `<div class="muted" style="font-size:10.5px;max-width:140px;">${esc(s.rejection_reason)}</div>` : ''}
          </td>
          <td>
            <div style="display:flex;gap:4px;flex-wrap:wrap;">
              <button class="btn ghost sm" type="button" onclick="openSocietyMembersModal(${s.club_id}, '${esc(s.club_name)}')">Members</button>
              ${isAdmin() && s.status === 'Pending' ? `
                <button class="btn ok sm" type="button" onclick="approveSocietyRegistration(${s.club_id}, '${esc(s.club_name)}')">Approve</button>
                <button class="btn bad sm" type="button" onclick="rejectSocietyRegistration(${s.club_id}, '${esc(s.club_name)}')">Reject</button>
              ` : ''}
            </div>
          </td>
        </tr>
      `).join("");
    } else {
      rowsHtml = `<tr><td colspan="6" class="empty">No student societies registered.</td></tr>`;
    }

    const modalHtml = `
      <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
        <div class="modal wide card" style="max-width:880px;margin:auto;">
          <div class="modal-head" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
            <div>
              <h3>Campus Societies &amp; Student Clubs</h3>
              <p class="sub" style="margin:0;">Registered campus student organizations, executives and booking privileges.</p>
            </div>
            <button class="btn ghost sm" type="button" onclick="closeModal()">✕</button>
          </div>
          <div class="modal-body">
            ${isAdmin() ? `
              <div style="display:flex;justify-content:flex-end;margin-bottom:14px">
                <button class="btn primary sm" type="button" onclick="openCreateSocietyModal()">+ Register New Society</button>
              </div>
            ` : ''}
            <div class="table-wrap">
              <table class="table">
                <thead>
                  <tr>
                    <th>Society Name</th>
                    <th>Department</th>
                    <th>Faculty In-Charge</th>
                    <th>Active Members</th>
                    <th>Status</th>
                    <th>Actions</th>
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
    toast("Failed to load societies: " + err.message, "err");
  }
}

async function openCreateSocietyModal() {
  const modalHtml = `
    <div class="modal-backdrop" onclick="if(event.target===this)openSocietiesModal()">
      <div class="modal card" style="max-width:480px;margin:auto;">
        <div class="modal-head" style="display:flex;justify-content:space-between;align-items:center;">
          <h3>Register Student Society</h3>
          <button class="btn ghost sm" type="button" onclick="openSocietiesModal()">✕</button>
        </div>
        <div class="modal-body" style="margin-top:14px;">
          <div class="field">
            <label for="socName">Society Name *</label>
            <input id="socName" class="input" placeholder="e.g. Robotics Club, Capella">
          </div>

          <div class="field">
            <label for="socDesc">Description</label>
            <textarea id="socDesc" class="input" rows="2" placeholder="Activities and purpose..."></textarea>
          </div>

          <div class="field">
            <label for="socYear">Established Year</label>
            <input id="socYear" class="input" type="number" value="${new Date().getFullYear()}">
          </div>

          <div class="modal-foot" style="display:flex;justify-content:flex-end;gap:8px;margin-top:20px;">
            <button class="btn ghost sm" type="button" onclick="openSocietiesModal()">Back</button>
            <button class="btn primary sm" type="button" onclick="submitCreateSociety()">Register</button>
          </div>
        </div>
      </div>
    </div>
  `;
  $("modalRoot").innerHTML = modalHtml;
}

async function submitCreateSociety() {
  const name = $("socName").value.trim();
  const desc = $("socDesc").value.trim();
  const year = parseInt($("socYear").value, 10) || null;

  if (!name) {
    toast("Society name is required.", "err");
    return;
  }

  try {
    await api.post("/societies", {
      club_name: name,
      description: desc,
      established_year: year
    });
    toast("Society registered successfully!", "ok");
    openSocietiesModal();
  } catch (err) {
    toast("Failed: " + err.message, "err");
  }
}

async function openSocietyMembersModal(clubId, clubName) {
  try {
    const members = await api.get(`/societies/${clubId}/members`);

    let mHtml = "";
    if (members.length) {
      mHtml = members.map(m => `
        <div class="slot" style="margin-bottom:8px;">
          <div>
            <b>${esc(m.user_name)}</b> <span class="muted" style="font-size:12px;">(${esc(m.user_email)})</span>
            <div style="margin-top:4px;">
              <span class="pill info">${esc(m.member_role)}</span>
              ${m.can_book ? '<span class="pill ok">Can Book</span>' : ''}
              ${m.can_manage ? '<span class="pill warn">Manager</span>' : ''}
            </div>
          </div>
          ${isAdmin() ? `
            <div>
              <button class="btn danger sm" type="button" onclick="removeSocietyMember(${clubId}, ${m.user_id}, '${esc(clubName)}')">Remove</button>
            </div>
          ` : ''}
        </div>
      `).join("");
    } else {
      mHtml = `<div class="empty">No members listed yet.</div>`;
    }

    const modalHtml = `
      <div class="modal-backdrop" onclick="if(event.target===this)openSocietiesModal()">
        <div class="modal card" style="max-width:540px;margin:auto;">
          <div class="modal-head" style="display:flex;justify-content:space-between;align-items:center;">
            <div>
              <h3>${esc(clubName)} — Members</h3>
              <p class="sub" style="margin:0;">${members.length} registered member(s)</p>
            </div>
            <button class="btn ghost sm" type="button" onclick="openSocietiesModal()">✕</button>
          </div>
          <div class="modal-body" style="margin-top:14px;">
            ${isAdmin() ? `
              <div style="display:flex;justify-content:flex-end;margin-bottom:12px;">
                <button class="btn primary sm" type="button" onclick="openAddMemberModal(${clubId}, '${esc(clubName)}')">+ Add Member</button>
              </div>
            ` : ''}
            <div style="max-height:320px;overflow-y:auto;">${mHtml}</div>
            <div class="modal-foot" style="margin-top:16px;text-align:right;">
              <button class="btn ghost sm" type="button" onclick="openSocietiesModal()">Back to Societies</button>
            </div>
          </div>
        </div>
      </div>
    `;
    $("modalRoot").innerHTML = modalHtml;
  } catch (err) {
    toast("Failed to load members: " + err.message, "err");
  }
}

async function openAddMemberModal(clubId, clubName) {
  try {
    const users = await api.get("/users");
    const userOpts = users.map(u =>
      `<option value="${u.user_id}">${esc(u.full_name)} (${esc(u.email)} · ${esc(u.role)})</option>`
    ).join("");

    const root = $("modalRoot");
    root.innerHTML = `
      <div class="modal-backdrop" onclick="if(event.target===this)openSocietyMembersModal(${clubId}, '${esc(clubName)}')">
        <div class="modal card" style="max-width:480px;margin:auto;">
          <h3>Add Member to ${esc(clubName)}</h3>
          <p class="sub">Select a campus user and assign society permissions.</p>

          <div class="field">
            <label>Campus User</label>
            <select id="newMemUserId" class="input">
              ${userOpts}
            </select>
          </div>

          <div class="field">
            <label>Member Role</label>
            <select id="newMemRole" class="input">
              <option value="President">President</option>
              <option value="Vice President">Vice President</option>
              <option value="Secretary">Secretary</option>
              <option value="Treasurer">Treasurer</option>
              <option value="Coordinator">Coordinator</option>
              <option value="Member" selected>Member</option>
            </select>
          </div>

          <div style="margin:16px 0;display:flex;flex-direction:column;gap:8px;">
            <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
              <input id="newMemCanBook" type="checkbox" checked>
              <span>Authorize to book spaces on behalf of ${esc(clubName)}</span>
            </label>
            <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
              <input id="newMemCanManage" type="checkbox" ${isAdmin() ? '' : 'disabled'}>
              <span>Society Manager (can add/remove members)</span>
            </label>
          </div>

          <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:20px;">
            <button class="btn ghost sm" type="button" onclick="openSocietyMembersModal(${clubId}, '${esc(clubName)}')">Cancel</button>
            <button class="btn primary sm" type="button" onclick="submitAddSocietyMember(${clubId}, '${esc(clubName)}')">Add Member</button>
          </div>
        </div>
      </div>
    `;
  } catch (err) {
    toast(err.message || "Failed to load user list.", "err");
  }
}

async function submitAddSocietyMember(clubId, clubName) {
  const userId = parseInt($("newMemUserId").value, 10);
  const role = $("newMemRole").value;
  const canBook = $("newMemCanBook").checked;
  const canManage = $("newMemCanManage").checked;

  try {
    await api.post(`/societies/${clubId}/members`, {
      user_id: userId,
      member_role: role,
      can_book: canBook,
      can_manage: canManage
    });
    toast("Member added to society.", "ok");
    openSocietyMembersModal(clubId, clubName);
  } catch (err) {
    toast(err.message || "Failed to add member.", "err");
  }
}

async function removeSocietyMember(clubId, userId, clubName) {
  if (!confirm("Are you sure you want to remove this member?")) return;
  try {
    await api.delete(`/societies/${clubId}/members/${userId}`);
    toast("Member removed.", "ok");
    openSocietyMembersModal(clubId, clubName);
  } catch (err) {
    toast(err.message, "err");
  }
}

async function approveSocietyRegistration(clubId, name) {
  if (!confirm(`Approve society "${name}"? It will become active for campus space bookings.`)) return;
  try {
    await api.post(`/societies/${clubId}/approve`);
    toast(`Society "${name}" approved successfully!`, "ok");
    openSocietiesModal();
  } catch (err) {
    toast("Failed to approve society: " + err.message, "err");
  }
}

async function rejectSocietyRegistration(clubId, name) {
  const reason = prompt(`Reason for rejecting society "${name}":`, "Organization details could not be verified.");
  if (reason === null) return;
  try {
    await api.post(`/societies/${clubId}/reject`, { reason });
    toast(`Society "${name}" rejected.`, "ok");
    openSocietiesModal();
  } catch (err) {
    toast("Failed to reject society: " + err.message, "err");
  }
}

// Global window registrations
window.openSocietiesModal = openSocietiesModal;
window.openCreateSocietyModal = openCreateSocietyModal;
window.submitCreateSociety = submitCreateSociety;
window.openSocietyMembersModal = openSocietyMembersModal;
window.openAddMemberModal = openAddMemberModal;
window.submitAddSocietyMember = submitAddSocietyMember;
window.removeSocietyMember = removeSocietyMember;
window.approveSocietyRegistration = approveSocietyRegistration;
window.rejectSocietyRegistration = rejectSocietyRegistration;
