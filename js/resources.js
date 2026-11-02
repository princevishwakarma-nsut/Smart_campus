let liveResources = [];
let liveCategories = [];

async function fetchResources(params = {}) {
  try {
    liveResources = await api.get("/resources", params);
    return liveResources;
  } catch (err) {
    toast("Failed to load resources: " + err.message, "err");
    return [];
  }
}

async function fetchCategories() {
  try {
    liveCategories = await api.get("/categories");
    return liveCategories;
  } catch (err) {
    console.error("Failed to load categories:", err);
    return [];
  }
}

function getResourceById(id) {
  return liveResources.find(r => r.resource_id === Number(id) || r.resource_id === id);
}

async function renderCatalog() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading resources from server...</div>`;
  
  if (!liveCategories.length) {
    await fetchCategories();
  }
  await fetchResources();

  let cats = ["All", ...liveCategories.map(c => c.category_name)];
  let catOpts = cats.map(c => `<option value="${esc(c)}" ${state.filters.category === c ? 'selected' : ''}>${esc(c)}</option>`).join("");

  let html = `
    <div class="filters">
      <input id="fq" class="input" placeholder="Search by space name, code, block or description..." value="${esc(state.filters.q)}" oninput="onFilterChange()">
      <select id="fc" class="input" onchange="onFilterChange()">${catOpts}</select>
      <input id="fd" class="input" type="date" value="${esc(state.filters.date)}" onchange="onFilterChange()">
      <input id="fst" class="input" type="time" value="${esc(state.filters.startTime)}" onchange="onFilterChange()" title="Start time">
      <input id="fet" class="input" type="time" value="${esc(state.filters.endTime)}" onchange="onFilterChange()" title="End time">
      ${(state.filters.q || state.filters.category !== 'All' || state.filters.date || state.filters.startTime || state.filters.endTime)
        ? `<button class="btn ghost sm" type="button" onclick="clearFilters()">Reset</button>` : ''}
    </div>
  `;

  // Filter in memory for instantaneous search, or re-query
  let list = liveResources.filter(r => {
    if (state.filters.category !== "All" && r.category_name !== state.filters.category) return false;
    if (state.filters.q) {
      const q = state.filters.q.toLowerCase();
      const match = (r.resource_name && r.resource_name.toLowerCase().includes(q)) ||
                    (r.resource_code && r.resource_code.toLowerCase().includes(q)) ||
                    (r.location && r.location.toLowerCase().includes(q)) ||
                    (r.description && r.description.toLowerCase().includes(q));
      if (!match) return false;
    }
    return true;
  });

  if (!list.length) {
    html += `<div class="empty">No matching resources found. Try adjusting your search or filters.</div>`;
    host.innerHTML = html;
    return;
  }

  html += `<div class="grid">`;
  for (const r of list) {
    const isAvail = r.status === "Available";
    const statusPill = isAvail
      ? `<span class="pill ok">Available</span>`
      : `<span class="pill ${r.status === 'Maintenance' ? 'warn' : 'bad'}">${esc(r.status)}</span>`;

    html += `
      <div class="card">
        <div class="card-head">
          <div>
            ${r.resource_code ? `<span class="code">${esc(r.resource_code)}</span>` : ""}
            <h3>${esc(r.resource_name)}</h3>
          </div>
          ${statusPill}
        </div>
        <div class="meta">
          <span class="tag">${esc(r.category_name || 'General')}</span>
          ${r.location ? `<span class="tag">📍 ${esc(r.location)}</span>` : ""}
          ${r.capacity ? `<span class="tag">👥 Cap: ${r.capacity}</span>` : ""}
        </div>
        <p class="muted" style="margin:4px 0">${esc(r.description || 'No description provided.')}</p>
        ${r.features && r.features.length ? `
          <div class="meta">
            ${r.features.map(f => `<span class="tag auto">✓ ${esc(f)}</span>`).join("")}
          </div>
        ` : ""}
        <div class="card-foot">
          <button class="btn ghost sm" type="button" onclick="openResourceSchedule(${r.resource_id})">View Timetable</button>
          ${isAvail ? `<button class="btn primary sm" type="button" onclick="openBookingModal(${r.resource_id})">Request slot</button>`
                    : `<button class="btn ghost sm" disabled>Unavailable</button>`}
        </div>
      </div>
    `;
  }
  html += `</div>`;
  host.innerHTML = html;
}

function onFilterChange() {
  state.filters.q = $("fq").value;
  state.filters.category = $("fc").value;
  state.filters.date = $("fd").value;
  state.filters.startTime = $("fst").value;
  state.filters.endTime = $("fet").value;
  renderCatalog();
}

function clearFilters() {
  state.filters = { q: "", category: "All", date: "", startTime: "", endTime: "" };
  renderCatalog();
}

async function renderResources() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading inventory...</div>`;
  
  if (!liveCategories.length) await fetchCategories();
  await fetchResources();

  $("topActions").innerHTML = `
    <button class="btn primary" type="button" onclick="openResourceModal()">+ Add resource</button>
  `;

  let html = `
    <div class="panel">
      <div class="panel-head">
        <h3>Campus Resources (${liveResources.length})</h3>
        <div class="actions">
          <input id="rq" class="input sm" placeholder="Filter inventory..." oninput="filterResourceTable(this.value)">
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Code</th>
            <th>Name</th>
            <th>Category</th>
            <th>Location</th>
            <th>Capacity</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody id="resTableBody">
  `;

  for (const r of liveResources) {
    const isAvail = r.status === "Available";
    const statusPill = isAvail
      ? `<span class="pill ok">Available</span>`
      : `<span class="pill ${r.status === 'Maintenance' ? 'warn' : 'bad'}">${esc(r.status)}</span>`;

    html += `
      <tr>
        <td><span class="code">${esc(r.resource_code || '—')}</span></td>
        <td class="cell-strong">${esc(r.resource_name)}</td>
        <td><span class="tag">${esc(r.category_name || 'General')}</span></td>
        <td>${esc(r.location || '—')}</td>
        <td>${r.capacity ? esc(r.capacity) : '—'}</td>
        <td>${statusPill}</td>
        <td>
          <div class="actions">
            <button class="btn ghost sm" type="button" onclick="openResourceModal(${r.resource_id})">Edit</button>
            ${isAvail ? `<button class="btn bad sm" type="button" onclick="quickToggleStatus(${r.resource_id}, 'Maintenance')">Maint.</button>`
                      : `<button class="btn ok sm" type="button" onclick="quickToggleStatus(${r.resource_id}, 'Available')">Enable</button>`}
          </div>
        </td>
      </tr>
    `;
  }

  html += `</tbody></table></div>`;
  host.innerHTML = html;
}

function filterResourceTable(val) {
  const q = val.toLowerCase();
  const rows = document.querySelectorAll("#resTableBody tr");
  rows.forEach(tr => {
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? "" : "none";
  });
}

async function quickToggleStatus(id, newStatus) {
  try {
    await api.patch(`/resources/${id}/status`, { status: newStatus });
    toast(`Resource status set to ${newStatus}`, "ok");
    renderResources();
  } catch (err) {
    toast(err.message, "err");
  }
}

async function openResourceModal(id) {
  const isEdit = !!id;
  const r = isEdit ? getResourceById(id) : null;

  if (!liveCategories.length) await fetchCategories();

  const catOpts = liveCategories.map(c =>
    `<option value="${c.category_id}" ${r && r.category_id === c.category_id ? 'selected' : ''}>${esc(c.category_name)}</option>`
  ).join("");

  const modalHtml = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <div class="modal">
        <div class="modal-head">
          <h2>${isEdit ? 'Edit Resource' : 'Add New Resource'}</h2>
          <button class="btn icon" type="button" onclick="closeModal()">✕</button>
        </div>
        <div class="modal-body">
          <label for="mrName">Resource Name *</label>
          <input id="mrName" class="input" value="${r ? esc(r.resource_name) : ''}" placeholder="e.g. Seminar Hall C">

          <label for="mrCode">Resource Code *</label>
          <input id="mrCode" class="input" value="${r ? esc(r.resource_code || '') : ''}" placeholder="e.g. SH-103">

          <label for="mrCategory">Category *</label>
          <select id="mrCategory" class="input">${catOpts}</select>

          <label for="mrLocation">Location *</label>
          <input id="mrLocation" class="input" value="${r ? esc(r.location || '') : ''}" placeholder="e.g. Block A, 2nd Floor">

          <label for="mrCap">Capacity</label>
          <input id="mrCap" class="input" type="number" min="1" value="${r && r.capacity ? esc(r.capacity) : ''}" placeholder="e.g. 60">

          <label for="mrStatus">Operational Status</label>
          <select id="mrStatus" class="input">
            <option value="Available" ${r && r.status === 'Available' ? 'selected' : ''}>Available</option>
            <option value="Maintenance" ${r && r.status === 'Maintenance' ? 'selected' : ''}>Maintenance</option>
            <option value="Inactive" ${r && r.status === 'Inactive' ? 'selected' : ''}>Inactive</option>
          </select>

          <label for="mrDesc">Description</label>
          <textarea id="mrDesc" class="input" rows="3" placeholder="Facilities, display, audio, rules...">${r ? esc(r.description || '') : ''}</textarea>

          <label for="mrFeatures">Features (comma separated)</label>
          <input id="mrFeatures" class="input" value="${r && r.features ? esc(r.features.join(', ')) : ''}" placeholder="e.g. Smart Board, Projector, AC, Workstations">

          <div class="modal-foot">
            <button class="btn ghost" type="button" onclick="closeModal()">Cancel</button>
            <button class="btn primary" type="button" onclick="saveResource(${isEdit ? r.resource_id : 'null'})">
              ${isEdit ? 'Save Changes' : 'Create Resource'}
            </button>
          </div>
        </div>
      </div>
    </div>
  `;
  $("modalRoot").innerHTML = modalHtml;
}

async function saveResource(id) {
  const name = $("mrName").value.trim();
  const code = $("mrCode").value.trim();
  const catId = Number($("mrCategory").value);
  const location = $("mrLocation").value.trim();
  const capVal = $("mrCap").value;
  const capacity = capVal ? parseInt(capVal, 10) : null;
  const status = $("mrStatus").value;
  const desc = $("mrDesc").value.trim();
  const featStr = $("mrFeatures").value.trim();
  const features = featStr ? featStr.split(",").map(f => f.trim()).filter(Boolean) : [];

  if (!name) {
    toast("Resource name is required.", "err");
    return;
  }
  if (!code) {
    toast("Resource code is required (e.g. LAB-101).", "err");
    return;
  }
  if (!location) {
    toast("Resource location is required (e.g. Block A).", "err");
    return;
  }

  const payload = {
    category_id: catId,
    resource_name: name,
    resource_code: code || null,
    location: location || null,
    capacity: capacity,
    status: status,
    description: desc || null,
    features: features
  };

  try {
    if (id) {
      await api.put(`/resources/${id}`, payload);
      toast("Resource updated successfully in MySQL!", "ok");
    } else {
      await api.post("/resources", payload);
      toast("Resource added to MySQL successfully!", "ok");
    }
    closeModal();
    if (state.view === "resources") {
      renderResources();
    } else {
      renderCatalog();
    }
  } catch (err) {
    toast("Error saving resource: " + err.message, "err");
  }
}

async function openResourceSchedule(id) {
  const r = getResourceById(id);
  if (!r) return;

  const todayStr = toLocalInput(new Date()).split("T")[0];
  try {
    const data = await api.get(`/timetable/resource/${id}`, { date: todayStr });
    
    let ttHtml = "";
    if (data.timetable_slots && data.timetable_slots.length) {
      ttHtml = data.timetable_slots.map(s => `
        <div class="slot">
          <time>${esc(s.start.substring(0, 5))} – ${esc(s.end.substring(0, 5))}</time>
          <div>
            <div class="t">${esc(s.title)}</div>
            <div class="s"><span class="pill warn">Class Timetable</span></div>
          </div>
        </div>
      `).join("");
    } else {
      ttHtml = `<div class="hint neutral">No regular academic classes scheduled on ${esc(data.day_of_week)}.</div>`;
    }

    let bkHtml = "";
    if (data.booking_slots && data.booking_slots.length) {
      bkHtml = data.booking_slots.map(b => `
        <div class="slot">
          <time>${fmtShort(b.start)}</time>
          <div>
            <div class="t">${esc(b.title)}</div>
            <div class="s">Booked by ${esc(b.user_name)} · <span class="pill ok">${esc(b.status)}</span></div>
          </div>
        </div>
      `).join("");
    } else {
      bkHtml = `<div class="hint ok">No booking reservations on this day.</div>`;
    }

    const modalHtml = `
      <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
        <div class="modal wide">
          <div class="modal-head">
            <div>
              <h2>${esc(r.resource_name)} — Schedule</h2>
              <div class="muted">${esc(data.day_of_week)}, ${esc(data.date)}</div>
            </div>
            <button class="btn icon" type="button" onclick="closeModal()">✕</button>
          </div>
          <div class="modal-body">
            <h3 style="font-size:14px;margin-bottom:8px">Recurring Academic Classes</h3>
            <div class="schedule" style="margin-bottom:16px">${ttHtml}</div>
            <h3 style="font-size:14px;margin-bottom:8px">Campus Bookings</h3>
            <div class="schedule">${bkHtml}</div>
            <div class="modal-foot">
              <button class="btn ghost" type="button" onclick="closeModal()">Close</button>
              <button class="btn primary" type="button" onclick="closeModal();openBookingModal(${r.resource_id})">Request this space</button>
            </div>
          </div>
        </div>
      </div>
    `;
    $("modalRoot").innerHTML = modalHtml;
  } catch (err) {
    toast("Failed to load schedule: " + err.message, "err");
  }
}

// Global window registrations
window.renderResources = renderResources;
window.renderCatalog = renderCatalog;
window.openResourceModal = openResourceModal;
window.saveResource = saveResource;
window.filterResourceTable = filterResourceTable;
window.quickToggleStatus = quickToggleStatus;
window.openResourceSchedule = openResourceSchedule;
window.onFilterChange = onFilterChange;
window.clearFilters = clearFilters;
