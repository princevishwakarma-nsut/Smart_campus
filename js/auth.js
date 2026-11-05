/* =========================================================
   Smart Campus — Authentication Module
   ========================================================= */

let currentUser = null;

function getCurrentUser() {
  if (currentUser) return currentUser;
  const raw = sessionStorage.getItem(CONFIG.STORAGE_USER_KEY);
  if (raw) {
    try {
      currentUser = JSON.parse(raw);
    } catch (e) {
      currentUser = null;
    }
  }
  return currentUser;
}

function setCurrentUser(user) {
  currentUser = user;
  if (user) {
    sessionStorage.setItem(CONFIG.STORAGE_USER_KEY, JSON.stringify(user));
  } else {
    sessionStorage.removeItem(CONFIG.STORAGE_USER_KEY);
  }
}

function isAdmin() {
  const u = getCurrentUser();
  return !!u && u.role === "Admin";
}

function isFaculty() {
  const u = getCurrentUser();
  return !!u && u.role === "Faculty";
}

function isStaff() {
  const u = getCurrentUser();
  return !!u && u.role === "Staff";
}

function isStudent() {
  const u = getCurrentUser();
  return !!u && u.role === "Student";
}

function canApprove() {
  return isAdmin();
}

async function doLogin() {
  const emailEl = $("loginEmail");
  const passEl = $("loginPass");
  if (!emailEl || !passEl) return;

  const email = emailEl.value.trim().toLowerCase();
  const password = passEl.value;

  if (!email || !password) {
    toast("Please enter your email and password.", "err");
    shakeLoginCard();
    return;
  }

  const btn = $("signInBtn");
  if (btn) {
    btn.classList.add("loading");
    btn.disabled = true;
  }

  try {
    const res = await api.post("/auth/login", { email, password });
    api.setToken(res.access_token);
    setCurrentUser(res.user);

    const card = $("loginCard");
    if (card) card.classList.add("exiting");

    setTimeout(() => {
      showAppScreen();
      showWelcomePop(res.user.name);
      if (card) card.classList.remove("exiting");
      if (btn) {
        btn.classList.remove("loading");
        btn.disabled = false;
      }
    }, 320);
  } catch (err) {
    shakeLoginCard();
    toast(err.message || "Invalid email or password", "err");
    if (btn) {
      btn.classList.remove("loading");
      btn.disabled = false;
    }
  }
}

function togglePasswordVisibility() {
  const input = $('loginPass');
  const button = document.querySelector('.password-toggle');
  if (!input || !button) return;
  const reveal = input.type === 'password';
  input.type = reveal ? 'text' : 'password';
  button.setAttribute('aria-label', reveal ? 'Hide password' : 'Show password');
  button.setAttribute('aria-pressed', String(reveal));
  input.focus();
}
window.togglePasswordVisibility = togglePasswordVisibility;

let currentAccountType = 'Student';

function setAccountType(type) {
  currentAccountType = type;

  // Toggle active class on tabs
  const tabStudent = $("typeBtnStudent");
  const tabFaculty = $("typeBtnFaculty");
  const tabSociety = $("typeBtnSociety");
  if (tabStudent) tabStudent.classList.toggle("active", type === 'Student');
  if (tabFaculty) tabFaculty.classList.toggle("active", type === 'Faculty');
  if (tabSociety) tabSociety.classList.toggle("active", type === 'Society');

  const userGroup = $("userFieldsGroup");
  const facultyFields = $("facultySpecificFields");
  const socGroup = $("societyFieldsGroup");
  const btn = $("registerBtn");
  const hint = $("regHintText");
  const deptLabel = $("regDeptLabel");

  if (type === 'Student') {
    if (userGroup) userGroup.classList.remove("hidden");
    if (facultyFields) facultyFields.classList.add("hidden");
    if (socGroup) socGroup.classList.add("hidden");
    if (deptLabel) deptLabel.textContent = "Department (Optional)";
    if (btn) btn.textContent = "Register Student Account";
    if (hint) hint.textContent = "Instant access to search and reserve campus facilities.";
  } else if (type === 'Faculty') {
    if (userGroup) userGroup.classList.remove("hidden");
    if (facultyFields) facultyFields.classList.remove("hidden");
    if (socGroup) socGroup.classList.add("hidden");
    if (deptLabel) deptLabel.textContent = "Department *";
    if (btn) btn.textContent = "Submit Faculty Request";
    if (hint) hint.textContent = "Faculty registration requires Administrator review before account activation.";
  } else if (type === 'Society') {
    if (userGroup) userGroup.classList.add("hidden");
    if (socGroup) socGroup.classList.remove("hidden");
    if (btn) btn.textContent = "Submit Society Request";
    if (hint) hint.textContent = "Societies require Administrator approval. Coordinators manage bookings via their personal account.";
  }
}

async function handleRegistrationSubmit() {
  if (currentAccountType === 'Student') {
    await doRegisterStudent();
  } else if (currentAccountType === 'Faculty') {
    await doRegisterFaculty();
  } else if (currentAccountType === 'Society') {
    await doRegisterSociety();
  }
}

async function doRegisterStudent() {
  const name = $("regName") ? $("regName").value.trim() : "";
  const email = $("regEmail") ? $("regEmail").value.trim().toLowerCase() : "";
  const deptEl = $("regDept");
  const deptId = (deptEl && deptEl.value) ? parseInt(deptEl.value, 10) : null;
  const phone = $("regPhone") ? $("regPhone").value.trim() : "";
  const pass = $("regPass") ? $("regPass").value : "";

  if (!name || !email || !pass) {
    toast("Please fill in your name, campus email and password.", "err");
    shakeLoginCard();
    return;
  }
  if (pass.length < 8) {
    toast("Password must be at least 8 characters long.", "err");
    shakeLoginCard();
    return;
  }

  const btn = $("registerBtn");
  if (btn) {
    btn.classList.add("loading");
    btn.disabled = true;
  }

  try {
    await api.post("/auth/register", {
      name: name,
      email: email,
      password: pass,
      role: "Student",
      department_id: deptId,
      phone_no: phone || null
    });

    // Auto log in after student registration
    const loginRes = await api.post("/auth/login", { email, password: pass });
    api.setToken(loginRes.access_token);
    setCurrentUser(loginRes.user);

    toast("Student account created successfully!", "ok");
    const card = $("loginCard");
    if (card) card.classList.add("exiting");

    setTimeout(() => {
      showAppScreen();
      showWelcomePop(loginRes.user.name);
      if (card) card.classList.remove("exiting");
      if (btn) {
        btn.classList.remove("loading");
        btn.disabled = false;
      }
    }, 320);
  } catch (err) {
    shakeLoginCard();
    toast(err.message || "Registration failed.", "err");
    if (btn) {
      btn.classList.remove("loading");
      btn.disabled = false;
    }
  }
}

async function doRegisterFaculty() {
  const name = $("regName") ? $("regName").value.trim() : "";
  const email = $("regEmail") ? $("regEmail").value.trim().toLowerCase() : "";
  const deptEl = $("regDept");
  const deptId = (deptEl && deptEl.value) ? parseInt(deptEl.value, 10) : null;
  const phone = $("regPhone") ? $("regPhone").value.trim() : "";
  const empId = $("regEmpId") ? $("regEmpId").value.trim() : "";
  const designation = $("regDesignation") ? $("regDesignation").value.trim() : "";
  const pass = $("regPass") ? $("regPass").value : "";

  if (!name || !email || !empId || !pass) {
    toast("Please enter your name, email, employee ID, and password.", "err");
    shakeLoginCard();
    return;
  }
  if (pass.length < 8) {
    toast("Password must be at least 8 characters long.", "err");
    shakeLoginCard();
    return;
  }

  const btn = $("registerBtn");
  if (btn) {
    btn.classList.add("loading");
    btn.disabled = true;
  }

  try {
    const res = await api.post("/auth/register/faculty", {
      name: name,
      email: email,
      password: pass,
      department_id: deptId,
      phone_no: phone || null,
      employee_id: empId,
      designation: designation || null
    });

    toast(res.message || "Faculty registration request submitted for admin review.", "ok");

    // Clear form and return to login screen
    if ($("regName")) $("regName").value = "";
    if ($("regEmail")) $("regEmail").value = "";
    if ($("regEmpId")) $("regEmpId").value = "";
    if ($("regDesignation")) $("regDesignation").value = "";
    if ($("regPhone")) $("regPhone").value = "";
    if ($("regPass")) $("regPass").value = "";

    setTimeout(() => {
      toggleAuthMode('login');
      if (btn) {
        btn.classList.remove("loading");
        btn.disabled = false;
      }
    }, 600);
  } catch (err) {
    shakeLoginCard();
    toast(err.message || "Faculty request failed.", "err");
    if (btn) {
      btn.classList.remove("loading");
      btn.disabled = false;
    }
  }
}

async function doRegisterSociety() {
  const name = $("regSocName") ? $("regSocName").value.trim() : "";
  const deptEl = $("regSocDept");
  const deptId = (deptEl && deptEl.value) ? parseInt(deptEl.value, 10) : null;
  const desc = $("regSocDesc") ? $("regSocDesc").value.trim() : "";
  const yearEl = $("regSocYear");
  const year = (yearEl && yearEl.value) ? parseInt(yearEl.value, 10) : new Date().getFullYear();
  const coordEmail = $("regSocCoordinatorEmail") ? $("regSocCoordinatorEmail").value.trim().toLowerCase() : "";

  if (!name || !coordEmail) {
    toast("Please enter the society name and coordinator campus email.", "err");
    shakeLoginCard();
    return;
  }

  const btn = $("registerBtn");
  if (btn) {
    btn.classList.add("loading");
    btn.disabled = true;
  }

  try {
    const res = await api.post("/auth/register/society", {
      club_name: name,
      department_id: deptId,
      description: desc || null,
      established_year: year,
      coordinator_email: coordEmail
    });

    toast(res.message || "Society registration request submitted for admin review.", "ok");

    // Clear form and return to login screen
    if ($("regSocName")) $("regSocName").value = "";
    if ($("regSocDesc")) $("regSocDesc").value = "";
    if ($("regSocCoordinatorEmail")) $("regSocCoordinatorEmail").value = "";

    setTimeout(() => {
      toggleAuthMode('login');
      if (btn) {
        btn.classList.remove("loading");
        btn.disabled = false;
      }
    }, 600);
  } catch (err) {
    shakeLoginCard();
    toast(err.message || "Society submission failed.", "err");
    if (btn) {
      btn.classList.remove("loading");
      btn.disabled = false;
    }
  }
}

async function toggleAuthMode(mode) {
  const loginArea = $("loginFormArea");
  const regArea = $("registerFormArea");
  if (!loginArea || !regArea) return;

  if (mode === 'register') {
    if ($("authHeading")) $("authHeading").textContent = "Create Your Account";
    if ($("authSubtitle")) $("authSubtitle").textContent = "Join your campus community and get connected to the spaces and resources you need.";
    loginArea.classList.add("hidden");
    regArea.classList.remove("hidden");
    setAccountType(currentAccountType || 'Student');

    // Populate departments dropdown if empty
    const deptSelect = $("regDept");
    const socDeptSelect = $("regSocDept");
    if ((deptSelect && deptSelect.options.length <= 1) || (socDeptSelect && socDeptSelect.options.length <= 1)) {
      try {
        const depts = await api.get("/departments").catch(() => api.get("/resources/departments").catch(() => []));
        const opts = `<option value="">-- General / Multi-Department --</option>` +
          depts.map(d => `<option value="${d.department_id}">${esc(d.name || d.department_name)}</option>`).join("");
        if (deptSelect) deptSelect.innerHTML = opts;
        if (socDeptSelect) socDeptSelect.innerHTML = opts;
      } catch (e) {
        // Fallback
      }
    }
  } else {
    if ($("authHeading")) $("authHeading").textContent = "Welcome Back";
    if ($("authSubtitle")) $("authSubtitle").textContent = "Log in to your account and seamlessly continue managing your campus resources.";
    regArea.classList.add("hidden");
    loginArea.classList.remove("hidden");
  }
}

async function logout() {
  const token = api.getToken();
  api.clearToken();
  setCurrentUser(null);
  document.documentElement.classList.remove("is-logged-in");
  $("app")?.classList.add("hidden");
  $("loginScreen")?.classList.remove("hidden");
  if ($("loginEmail")) $("loginEmail").value = "";
  if ($("loginPass")) $("loginPass").value = "";
  if (typeof toggleAuthMode === "function") toggleAuthMode("login");

  if (token) {
    try {
      await fetch(`${api.baseUrl}/auth/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` }
      });
    } catch (err) {
      console.error("Could not revoke the current session token:", err);
      toast("Signed out locally, but the server could not revoke this session.", "err");
    }
  }
}
window.logout = logout;

// Explicit DOM listener backup for the sign out button
document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("signOutBtn");
  if (btn) {
    btn.onclick = (e) => {
      e.preventDefault();
      logout();
    };
  }
});

function showLoginScreen() {
  document.documentElement.classList.remove("is-logged-in");
  document.documentElement.classList.remove("student-theme");
  const appEl = $("app");
  if (appEl) appEl.classList.add("hidden");
  const loginEl = $("loginScreen");
  if (loginEl) loginEl.classList.remove("hidden");
  if (typeof toggleAuthMode === "function") toggleAuthMode('login');
  const card = $("loginCard");
  if (card) card.classList.remove("exiting", "shake");
  const btn = $("signInBtn");
  if (btn) {
    btn.classList.remove("loading");
    btn.disabled = false;
  }
}

function showAppScreen() {
  const user = getCurrentUser();
  if (!user) return showLoginScreen();

  document.documentElement.classList.add("is-logged-in");
  document.documentElement.classList.toggle("student-theme", user.role === "Student" || user.role === "Faculty");
  $("loginScreen").classList.add("hidden");
  const appEl = $("app");
  appEl.classList.remove("hidden");
  appEl.classList.remove("entering");
  void appEl.offsetWidth;
  appEl.classList.add("entering");

  $("uName").textContent = user.name;
  $("uRole").textContent = `${user.role}${user.department_name ? " · " + user.department_name : ""}`;

  renderNav();
  go(homeViewFor(user.role));
  fetchUnreadNotificationCount();
}

function homeViewFor(role) {
  if (role === "Admin") return "adminDash";
  if (role === "Faculty") return "facultyDash";
  if (role === "Staff") return "checkins";
  return "catalog";
}

function shakeLoginCard() {
  const card = $("loginCard");
  if (!card) return;
  card.classList.remove("shake");
  void card.offsetWidth;
  card.classList.add("shake");
  setTimeout(() => card.classList.remove("shake"), 520);
}

function showWelcomePop(name) {
  const existing = document.querySelector(".welcome-pop");
  if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
  const w = document.createElement("div");
  w.className = "welcome-pop";
  w.innerHTML = `
    <div class="wp-mark">SC</div>
    <div class="wp-text">Welcome back, <b>${esc(name.split(" ")[0])}</b></div>
  `;
  document.body.appendChild(w);
  setTimeout(() => {
    if (w.parentNode) {
      w.classList.add("leaving");
      setTimeout(() => { if (w.parentNode) w.parentNode.removeChild(w); }, 420);
    }
  }, 1900);
}

// Deprecated demo functions retained as harmless stubs for compatibility
function renderQuickAccounts() {}
function quickLogin() {}

async function openUserProfileModal() {
  const modalRoot = $("modalRoot");
  if (!modalRoot) return;

  try {
    const user = await api.get("/auth/me");
    setCurrentUser(user);

    modalRoot.innerHTML = `
      <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
        <div class="modal card" style="max-width:440px; margin:auto;">
          <div class="modal-head" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
            <div>
              <h3>My Account Profile</h3>
              <p class="sub" style="margin:0;">View and manage your campus account details</p>
            </div>
            <button class="btn ghost sm" type="button" onclick="closeModal()">✕</button>
          </div>
          <div class="modal-body">
            <div style="display:flex; align-items:center; gap:12px; padding:12px; background:rgba(99,102,241,0.06); border-radius:8px; margin-bottom:14px;">
              <div style="width:40px; height:40px; border-radius:50%; background:var(--primary); color:#fff; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:16px;">
                ${esc(user.name.charAt(0).toUpperCase())}
              </div>
              <div>
                <div style="font-weight:700; font-size:15px;">${esc(user.name)}</div>
                <div class="muted" style="font-size:12px;">${esc(user.email)} · <span class="pill info" style="font-size:10px; padding:1px 6px;">${esc(user.role)}</span></div>
              </div>
            </div>

            <div class="field" style="margin-bottom:12px;">
              <label for="profName" style="display:block; font-weight:600; margin-bottom:4px;">Full Name</label>
              <input id="profName" class="input" type="text" value="${esc(user.name)}" style="width:100%;">
            </div>

            <div class="field" style="margin-bottom:12px;">
              <label style="display:block; font-weight:600; margin-bottom:4px;">Campus Email</label>
              <input class="input" type="email" value="${esc(user.email)}" disabled style="width:100%; opacity:0.75; cursor:not-allowed;">
            </div>

            <div class="field" style="margin-bottom:12px;">
              <label style="display:block; font-weight:600; margin-bottom:4px;">Department</label>
              <input class="input" type="text" value="${esc(user.department_name || 'General / Unassigned')}" disabled style="width:100%; opacity:0.75; cursor:not-allowed;">
            </div>

            <div class="field" style="margin-bottom:16px;">
              <label for="profPhone" style="display:block; font-weight:600; margin-bottom:4px;">Phone Number</label>
              <input id="profPhone" class="input" type="tel" value="${esc(user.phone_no || '')}" placeholder="+91 98765 43210" style="width:100%;">
            </div>
          </div>
          <div class="modal-foot" style="display:flex; justify-content:space-between; align-items:center; margin-top:8px;">
            <button class="btn ghost sm" type="button" onclick="openChangePasswordModal()">Change Password</button>
            <div style="display:flex; gap:8px;">
              <button class="btn ghost sm" type="button" onclick="closeModal()">Cancel</button>
              <button class="btn primary sm" type="button" onclick="submitUpdateProfile(${user.user_id})">Save Changes</button>
            </div>
          </div>
        </div>
      </div>
    `;
  } catch (err) {
    toast("Failed to load profile: " + err.message, "err");
  }
}

async function submitUpdateProfile(userId) {
  const name = $("profName").value.trim();
  const phone = $("profPhone").value.trim();

  if (!name) {
    toast("Full name cannot be empty.", "err");
    return;
  }

  try {
    const updated = await api.put(`/users/${userId}`, {
      name: name,
      phone_no: phone || null
    });
    setCurrentUser(updated);
    $("uName").textContent = updated.name;
    toast("Profile updated successfully!", "ok");
    closeModal();
  } catch (err) {
    toast(err.message || "Failed to update profile.", "err");
  }
}

window.openUserProfileModal = openUserProfileModal;
window.submitUpdateProfile = submitUpdateProfile;

function openChangePasswordModal() {
  const modalRoot = $("modalRoot");
  if (!modalRoot) return;

  modalRoot.innerHTML = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <div class="modal card" style="max-width:400px; margin:auto;">
        <div class="modal-head" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
          <div>
            <h3>Change Password</h3>
            <p class="sub" style="margin:0;">Update your account password</p>
          </div>
          <button class="btn ghost sm" type="button" onclick="closeModal()">✕</button>
        </div>
        <div class="modal-body">
          <div class="field" style="margin-bottom:12px;">
            <label for="chgCurPass" style="display:block; font-weight:600; margin-bottom:4px;">Current Password *</label>
            <input id="chgCurPass" class="input" type="password" style="width:100%;">
          </div>
          <div class="field" style="margin-bottom:12px;">
            <label for="chgNewPass" style="display:block; font-weight:600; margin-bottom:4px;">New Password (min 8 chars) *</label>
            <input id="chgNewPass" class="input" type="password" style="width:100%;">
          </div>
          <div class="field" style="margin-bottom:16px;">
            <label for="chgConfPass" style="display:block; font-weight:600; margin-bottom:4px;">Confirm New Password *</label>
            <input id="chgConfPass" class="input" type="password" style="width:100%;">
          </div>
        </div>
        <div class="modal-foot" style="display:flex; justify-content:flex-end; gap:8px;">
          <button class="btn ghost sm" type="button" onclick="closeModal()">Cancel</button>
          <button class="btn primary sm" type="button" onclick="submitChangePassword()">Change Password</button>
        </div>
      </div>
    </div>
  `;
}

async function submitChangePassword() {
  const curPass = $("chgCurPass").value;
  const newPass = $("chgNewPass").value;
  const confPass = $("chgConfPass").value;

  if (!curPass || !newPass) {
    toast("Please enter current and new password.", "err");
    return;
  }

  if (newPass.length < 8) {
    toast("New password must be at least 8 characters long.", "err");
    return;
  }

  if (newPass !== confPass) {
    toast("New password and confirmation do not match.", "err");
    return;
  }

  try {
    const res = await api.post("/auth/change-password", {
      current_password: curPass,
      new_password: newPass
    });
    toast(res.message || "Password changed! Please log in again.", "ok");
    closeModal();
    api.clearToken();
    showLoginScreen();
  } catch (err) {
    toast(err.message || "Failed to change password.", "err");
  }
}

window.openChangePasswordModal = openChangePasswordModal;
window.submitChangePassword = submitChangePassword;
