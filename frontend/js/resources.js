let liveResources = [];
let liveCategories = [];
let liveEquipmentInventory = [];
let inventoryActiveTab = "resources";

function sortInventoryNewestFirst(items, idField) {
  return [...items].sort((a, b) => {
    const timeA = Date.parse(a.created_at || "") || 0;
    const timeB = Date.parse(b.created_at || "") || 0;
    return timeB - timeA || Number(b[idField]) - Number(a[idField]);
  });
}

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
  
  const catalogFetches = [];
  if (!liveCategories.length) catalogFetches.push(fetchCategories());
  catalogFetches.push(fetchResources());
  await Promise.all(catalogFetches);

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
  $("topActions").innerHTML = "";

  try {
    const categoryPromise = (liveCategories && liveCategories.length > 0) ? Promise.resolve(liveCategories) : api.get("/categories");
    const [categories, resources, equipment] = await Promise.all([
      categoryPromise,
      api.get("/resources"),
      api.get("/equipment")
    ]);
    liveCategories = categories;
    liveResources = resources;
    liveEquipmentInventory = equipment;
    const resourceCategories = liveCategories.map(category => `
      <option value="${category.category_id}">${esc(category.category_name)}</option>
    `).join("");
    const equipmentCategories = [...new Set(liveEquipmentInventory.map(item => item.category).filter(Boolean))]
      .sort().map(category => `<option value="${esc(category)}">${esc(category)}</option>`).join("");
    const activeTab = inventoryActiveTab === "equipment" ? "equipment" : "resources";
    const resourceRows = sortInventoryNewestFirst(liveResources, "resource_id").map(resource => {
      const statePill = resource.status === "Available"
        ? `<span class="pill ok">Available</span>`
        : `<span class="pill ${resource.status === "Maintenance" ? "warn" : "bad"}">${esc(resource.status)}</span>`;
      return `<tr data-category="${resource.category_id}" data-status="${esc(resource.status)}">
        <td><span class="code">${esc(resource.resource_code || "—")}</span></td>
        <td><div class="cell-strong">${esc(resource.resource_name)}</div><div class="muted">${esc(resource.description || "")}</div></td>
        <td>${esc(resource.category_name || "General")}</td>
        <td>${esc(resource.location || "—")}</td>
        <td>${resource.capacity ? esc(resource.capacity) : "—"}</td>
        <td>${statePill}</td>
        <td><div class="actions">
          <button class="btn ghost sm" type="button" onclick="openResourceDetails(${resource.resource_id})">Details</button>
          <button class="btn ghost sm" type="button" onclick="openResourceSchedule(${resource.resource_id})">Availability</button>
          <button class="btn primary sm" type="button" onclick="openResourceModal(${resource.resource_id})">Edit</button>
        </div></td>
      </tr>`;
    }).join("");
    const equipmentRows = sortInventoryNewestFirst(liveEquipmentInventory, "item_id").map(item => {
      const availability = item.is_active ? (item.availability_status || "Available") : "Inactive";
      const availabilityClass = availability === "Available" ? "ok" : (availability === "Inactive" ? "bad" : "warn");
      const condition = item.condition_status || (item.damaged_quantity ? "Damaged" : "Good");
      return `<tr data-category="${esc(item.category || "Other")}" data-status="${esc(availability)}" data-condition="${esc(condition)}">
        <td><div class="cell-strong">${esc(item.item_name)}</div><div class="code">${esc(item.item_code || "—")}</div></td>
        <td>${esc(item.serial_no || "—")}</td>
        <td>${esc(item.category || "Other")}</td>
        <td>${esc(item.location || "—")}</td>
        <td>${item.available_quantity ?? 0} / ${item.total_quantity} ${esc(item.unit || "Piece")}</td>
        <td><span class="pill ${availabilityClass}">${esc(availability)}</span></td>
        <td><span class="pill ${condition === "Good" ? "ok" : "warn"}">${esc(condition)}</span></td>
        <td><div class="actions">
          <button class="btn ghost sm" type="button" onclick="openEquipmentDetails(${item.item_id})">Details</button>
          ${item.availability_status === "Issued" || item.reserved_quantity > 0 ? `<button class="btn warn sm" type="button" onclick="openReturnEquipmentModal(${item.item_id})">Return</button>` : ""}
          <button class="btn primary sm" type="button" onclick="openEditEquipmentModal(${item.item_id})">Edit</button>
        </div></td>
      </tr>`;
    }).join("");

    host.innerHTML = `
      <div class="inventory-tabs" role="tablist" aria-label="Inventory type">
        <button type="button" role="tab" aria-selected="${activeTab === "resources"}" class="${activeTab === "resources" ? "active" : ""}" onclick="setInventoryTab('resources')">
          Resources <span class="inventory-count">${liveResources.length}</span>
        </button>
        <button type="button" role="tab" aria-selected="${activeTab === "equipment"}" class="${activeTab === "equipment" ? "active" : ""}" onclick="setInventoryTab('equipment')">
          Equipment <span class="inventory-count">${liveEquipmentInventory.length}</span>
        </button>
      </div>
      ${activeTab === "resources" ? `
        <section class="panel inventory-panel">
          <div class="inventory-heading">
            <div><h2>Campus Resources</h2><p class="muted">Manage bookable spaces, facilities, features and operational status.</p></div>
            <div class="actions">
              <button class="btn primary" type="button" onclick="openResourceModal()">+ Add Resource</button>
            </div>
          </div>
          <div class="inventory-filters">
            <input id="resourceInventorySearch" class="input sm" placeholder="Search resources..." oninput="filterResourceInventory()">
            <select id="resourceInventoryCategory" class="input sm" onchange="filterResourceInventory()"><option value="">All categories</option>${resourceCategories}</select>
            <select id="resourceInventoryStatus" class="input sm" onchange="filterResourceInventory()"><option value="">All availability</option><option>Available</option><option>Maintenance</option><option>Inactive</option></select>
            <span class="inventory-result-count" id="resourceInventoryCount">${liveResources.length} resources</span>
          </div>
          <div class="table-wrap inventory-table"><table><thead><tr><th>Code</th><th>Resource</th><th>Category</th><th>Location</th><th>Capacity</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody id="resTableBody">${resourceRows || `<tr><td class="empty" colspan="7">No resources found.</td></tr>`}</tbody>
          </table></div>
        </section>
      ` : `
        <section class="panel inventory-panel">
          <div class="inventory-heading">
            <div><h2>Equipment Inventory</h2><p class="muted">Track physical items, stock availability, condition and issue/return activity.</p></div>
            <button class="btn primary" type="button" onclick="openAddEquipmentModal()">+ Add Equipment Item</button>
          </div>
          <div class="inventory-filters">
            <input id="equipmentInventorySearch" class="input sm" placeholder="Search equipment..." oninput="filterEquipmentInventory()">
            <select id="equipmentInventoryCategory" class="input sm" onchange="filterEquipmentInventory()"><option value="">All categories</option>${equipmentCategories}</select>
            <select id="equipmentInventoryStatus" class="input sm" onchange="filterEquipmentInventory()"><option value="">All availability</option><option>Available</option><option>Issued</option><option>Maintenance</option><option>Inactive</option></select>
            <select id="equipmentInventoryCondition" class="input sm" onchange="filterEquipmentInventory()"><option value="">All conditions</option><option>Good</option><option>Damaged</option></select>
            <span class="inventory-result-count" id="equipmentInventoryCount">${liveEquipmentInventory.length} equipment items</span>
          </div>
          <div class="table-wrap inventory-table"><table><thead><tr><th>Item</th><th>Serial / Tag</th><th>Category</th><th>Storage</th><th>Available / Total</th><th>Availability</th><th>Condition</th><th>Actions</th></tr></thead>
            <tbody id="equipmentInventoryBody">${equipmentRows || `<tr><td class="empty" colspan="8">No equipment items found.</td></tr>`}</tbody>
          </table></div>
        </section>
      `}`;
  } catch (err) {
    host.innerHTML = `<div class="empty">Failed to load inventory: ${esc(err.message)}</div>`;
  }
}

function setInventoryTab(tab) {
  inventoryActiveTab = tab;
  renderResources();
}

function filterResourceInventory() {
  const q = ($("resourceInventorySearch")?.value || "").trim().toLowerCase();
  const category = $("resourceInventoryCategory")?.value || "";
  const status = $("resourceInventoryStatus")?.value || "";
  let visible = 0;
  document.querySelectorAll("#resTableBody tr[data-category]").forEach(row => {
    const matches = row.textContent.toLowerCase().includes(q) &&
      (!category || row.dataset.category === category) &&
      (!status || row.dataset.status === status);
    row.hidden = !matches;
    if (matches) visible += 1;
  });
  if ($("resourceInventoryCount")) $("resourceInventoryCount").textContent = `${visible} of ${liveResources.length} resources`;
}

function filterEquipmentInventory() {
  const q = ($("equipmentInventorySearch")?.value || "").trim().toLowerCase();
  const category = $("equipmentInventoryCategory")?.value || "";
  const status = $("equipmentInventoryStatus")?.value || "";
  const condition = $("equipmentInventoryCondition")?.value || "";
  let visible = 0;
  document.querySelectorAll("#equipmentInventoryBody tr[data-category]").forEach(row => {
    const matches = row.textContent.toLowerCase().includes(q) &&
      (!category || row.dataset.category === category) &&
      (!status || row.dataset.status === status) &&
      (!condition || row.dataset.condition === condition);
    row.hidden = !matches;
    if (matches) visible += 1;
  });
  if ($("equipmentInventoryCount")) $("equipmentInventoryCount").textContent = `${visible} of ${liveEquipmentInventory.length} equipment items`;
}

async function openOperatingHoursModal() {
  try {
    const [categories, resources, exceptions] = await Promise.all([
      api.get("/categories"),
      api.get("/resources"),
      api.get("/resources/operating-hours/exceptions")
    ]);
    liveCategories = categories;
    liveResources = resources;
    const categoryOptions = categories.map(category => `
      <label class="operating-target-option">
        <input type="checkbox" class="oh-category" value="${category.category_id}">
        <span>${esc(category.category_name)}</span>
      </label>
    `).join("");
    const resourceOptions = resources.map(resource => `
      <label class="operating-target-option" data-search="${esc(`${resource.resource_name} ${resource.category_name || ""}`.toLowerCase())}">
        <input type="checkbox" class="oh-resource" value="${resource.resource_id}">
        <span>${esc(resource.resource_name)} <small>${esc(resource.category_name || "Uncategorized")}</small></span>
      </label>
    `).join("");
    const weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
    $("modalRoot").innerHTML = `
      <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
        <section class="modal card operating-hours-modal" role="dialog" aria-modal="true" aria-labelledby="operatingHoursTitle">
          <header class="panel-head operating-hours-header">
            <div><h3 id="operatingHoursTitle">Resource Operating Hours</h3>
              <p class="muted">Set recurring hours in one operation. Unselected weekdays are closed.</p></div>
            <button class="btn icon" type="button" aria-label="Close" onclick="closeModal()">✕</button>
          </header>
          <div class="operating-hours-body">
            <section class="operating-hours-section">
              <h4>Apply operating hours to</h4>
              <label class="operating-target-option operating-all-target">
                <input id="ohAllResources" type="checkbox">
                <span>All resources</span>
              </label>
              <div class="operating-target-columns">
                <div><b>Categories</b><div class="operating-target-list">${categoryOptions || `<span class="muted">No categories found.</span>`}</div></div>
                <div><b>Individual resources</b>
                  <input id="ohResourceSearch" class="input sm operating-resource-search" type="search" aria-label="Search operating-hours resources" placeholder="Search resources..." oninput="filterOperatingResources()">
                  <div class="operating-target-list" id="ohResourceList">${resourceOptions || `<span class="muted">No resources found.</span>`}</div>
                </div>
              </div>
            </section>
            <section class="operating-hours-section">
              <h4>Weekly schedule</h4>
              <div class="operating-days-heading">
                <label class="operating-target-option"><input id="ohAllDays" type="checkbox" checked onchange="toggleAllOperatingDays(this.checked)"><span>All days</span></label>
                <span class="muted">Opening and closing times can cross midnight.</span>
              </div>
              <label class="operating-target-option operating-schedule-active">
                <input id="ohScheduleActive" type="checkbox" checked>
                <span>Schedule active</span>
              </label>
              <div class="operating-weekdays">${weekdays.map(day => `
                <label class="operating-target-option"><input class="oh-weekday" type="checkbox" value="${day}" checked onchange="syncAllOperatingDays()"><span>${day}</span></label>
              `).join("")}</div>
              <div class="operating-time-grid">
                <label>Opening time<input id="ohOpenTime" class="input sm" type="time" value="08:00"></label>
                <label>Closing time<input id="ohCloseTime" class="input sm" type="time" value="18:00"></label>
              </div>
              <p class="muted operating-help">Example: select All days and 08:00–18:00 for the common campus schedule.</p>
              <div class="actions operating-hours-save"><button class="btn primary" type="button" onclick="saveOperatingHours()">Apply weekly schedule</button></div>
            </section>
            <section class="operating-hours-section">
              <h4>Holiday or special-event exception</h4>
              <div class="operating-exception-grid">
                <label>Start date<input id="ohExceptionStart" class="input sm" type="date"></label>
                <label>End date<input id="ohExceptionEnd" class="input sm" type="date"></label>
              </div>
              <label class="operating-target-option operating-closed-exception">
                <input id="ohExceptionClosed" type="checkbox" checked onchange="toggleOperatingExceptionHours(this.checked)">
                <span>Closed for the selected dates</span>
              </label>
              <div id="ohExceptionHours" class="operating-time-grid hidden">
                <label>Opening time<input id="ohExceptionOpen" class="input sm" type="time" value="08:00"></label>
                <label>Closing time<input id="ohExceptionClose" class="input sm" type="time" value="18:00"></label>
              </div>
              <label class="operating-exception-reason">Reason<input id="ohExceptionReason" class="input sm" maxlength="255" placeholder="Holiday, examination, special event..."></label>
              <div class="actions operating-hours-save"><button class="btn ghost" type="button" onclick="createOperatingHoursException()">Add exception</button></div>
              <div class="operating-exceptions-list" id="operatingExceptionsList">${renderOperatingExceptions(exceptions)}</div>
            </section>
          </div>
          <footer class="actions operating-hours-footer">
            <span class="muted">Changes are applied transactionally and audited.</span>
            <button class="btn ghost" type="button" onclick="closeModal()">Close</button>
          </footer>
        </section>
      </div>`;
  } catch (error) {
    toast(`Could not load operating hours: ${error.message}`, "err");
  }
}

function renderOperatingExceptions(exceptions) {
  if (!exceptions.length) return `<p class="muted">No active date exceptions.</p>`;
  return exceptions.map(exception => `
    <article class="operating-exception-row">
      <div><b>${esc(exception.resource_name)}</b><span>${esc(exception.start_date)} – ${esc(exception.end_date)}</span>
        <small>${exception.is_closed ? "Closed" : `${esc(exception.open_time)}–${esc(exception.close_time)}`} · ${esc(exception.reason)}</small></div>
      ${exception.status === "Active" ? `<button class="btn ghost sm" type="button" onclick="cancelOperatingHoursException(${exception.exception_id})">Cancel</button>` : ""}
    </article>
  `).join("");
}

function filterOperatingResources() {
  const query = ($("ohResourceSearch")?.value || "").trim().toLowerCase();
  document.querySelectorAll("#ohResourceList .operating-target-option").forEach(option => {
    option.hidden = !option.dataset.search.includes(query);
  });
}

function toggleAllOperatingDays(checked) {
  document.querySelectorAll(".oh-weekday").forEach(input => { input.checked = checked; });
}

function syncAllOperatingDays() {
  const weekdays = [...document.querySelectorAll(".oh-weekday")];
  $("ohAllDays").checked = weekdays.every(input => input.checked);
  $("ohAllDays").indeterminate = weekdays.some(input => input.checked) && !$("ohAllDays").checked;
}

function toggleOperatingExceptionHours(closed) {
  $("ohExceptionHours")?.classList.toggle("hidden", closed);
}

function getOperatingHoursTargets() {
  return {
    all_resources: $("ohAllResources").checked,
    category_ids: [...document.querySelectorAll(".oh-category:checked")].map(input => Number(input.value)),
    resource_ids: [...document.querySelectorAll(".oh-resource:checked")].map(input => Number(input.value)),
  };
}

function validateOperatingHoursTargets(targets) {
  if (!targets.all_resources && !targets.category_ids.length && !targets.resource_ids.length) {
    toast("Select all resources, at least one category, or individual resources.", "err");
    return false;
  }
  return true;
}

async function saveOperatingHours() {
  const targets = getOperatingHoursTargets();
  if (!validateOperatingHoursTargets(targets)) return;
  const weekdays = [...document.querySelectorAll(".oh-weekday:checked")].map(input => input.value);
  const closedDays = [...document.querySelectorAll(".oh-weekday:not(:checked)")].map(input => input.value);
  if (weekdays.length && (!$("ohOpenTime").value || !$("ohCloseTime").value || $("ohOpenTime").value === $("ohCloseTime").value)) {
    toast("Choose different opening and closing times.", "err");
    return;
  }
  try {
    const result = await api.put("/resources/operating-hours/bulk", {
      ...targets,
      is_active: $("ohScheduleActive").checked,
      weekdays,
      closed_days: closedDays,
      open_time: weekdays.length ? $("ohOpenTime").value : null,
      close_time: weekdays.length ? $("ohCloseTime").value : null,
    });
    toast(`Operating hours applied to ${result.resource_count} resource(s).`, "ok");
  } catch (error) {
    toast(`Could not apply operating hours: ${error.message}`, "err");
  }
}

async function createOperatingHoursException() {
  const targets = getOperatingHoursTargets();
  if (!validateOperatingHoursTargets(targets)) return;
  const startDate = $("ohExceptionStart").value;
  const endDate = $("ohExceptionEnd").value;
  const isClosed = $("ohExceptionClosed").checked;
  const reason = $("ohExceptionReason").value.trim();
  if (!startDate || !endDate || endDate < startDate || !reason) {
    toast("Choose a valid date range and enter an exception reason.", "err");
    return;
  }
  if (!isClosed && (!$("ohExceptionOpen").value || !$("ohExceptionClose").value ||
      $("ohExceptionOpen").value === $("ohExceptionClose").value)) {
    toast("Choose different opening and closing times for the exception.", "err");
    return;
  }
  try {
    const result = await api.post("/resources/operating-hours/exceptions", {
      ...targets,
      start_date: startDate,
      end_date: endDate,
      is_closed: isClosed,
      open_time: isClosed ? null : $("ohExceptionOpen").value,
      close_time: isClosed ? null : $("ohExceptionClose").value,
      reason,
    });
    const exceptions = await api.get("/resources/operating-hours/exceptions");
    $("operatingExceptionsList").innerHTML = renderOperatingExceptions(exceptions);
    toast(`Date exception applied to ${result.resource_count} resource(s).`, "ok");
  } catch (error) {
    toast(`Could not add operating-hours exception: ${error.message}`, "err");
  }
}

async function cancelOperatingHoursException(exceptionId) {
  try {
    await api.patch(`/resources/operating-hours/exceptions/${exceptionId}/cancel`);
    const exceptions = await api.get("/resources/operating-hours/exceptions");
    $("operatingExceptionsList").innerHTML = renderOperatingExceptions(exceptions);
    toast("Operating-hours exception cancelled; its history was retained.", "ok");
  } catch (error) {
    toast(`Could not cancel exception: ${error.message}`, "err");
  }
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
          <div class="form-grid">
            <div class="field"><label for="mrName">Resource Name *</label>
              <input id="mrName" class="input" value="${r ? esc(r.resource_name) : ''}" placeholder="e.g. Seminar Hall C"></div>
            <div class="field"><label for="mrCode">Resource Code *</label>
              <input id="mrCode" class="input" value="${r ? esc(r.resource_code || '') : ''}" placeholder="e.g. SH-103"></div>
            <div class="field"><label for="mrCategory">Category *</label>
              <select id="mrCategory" class="input">${catOpts}</select></div>
            <div class="field"><label for="mrLocation">Location *</label>
              <input id="mrLocation" class="input" value="${r ? esc(r.location || '') : ''}" placeholder="e.g. Block A, 2nd Floor"></div>
            <div class="field"><label for="mrHours">Operating Hours</label>
              <input id="mrHours" class="input" value="${r ? esc(r.operating_hours || '') : ''}" maxlength="255" placeholder="e.g. Mon-Fri, 08:00-20:00"></div>
            <div class="field"><label for="mrCap">Capacity</label>
              <input id="mrCap" class="input" type="number" min="1" value="${r && r.capacity ? esc(r.capacity) : ''}" placeholder="e.g. 60"></div>
            <div class="field"><label for="mrStatus">Operational Status</label>
              <select id="mrStatus" class="input">
                <option value="Available" ${r && r.status === 'Available' ? 'selected' : ''}>Available</option>
                <option value="Maintenance" ${r && r.status === 'Maintenance' ? 'selected' : ''}>Maintenance</option>
                <option value="Inactive" ${r && r.status === 'Inactive' ? 'selected' : ''}>Inactive</option>
              </select></div>
            <div class="field inventory-field-full"><label for="mrDesc">Description</label>
              <textarea id="mrDesc" class="input" rows="2" placeholder="Facilities, display, audio, rules...">${r ? esc(r.description || '') : ''}</textarea></div>
            <div class="field inventory-field-full"><label for="mrFeatures">Features (comma separated)</label>
              <input id="mrFeatures" class="input" value="${r && r.features ? esc(r.features.join(', ')) : ''}" placeholder="e.g. Smart Board, Projector, AC, Workstations"></div>
          </div>

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
  const operatingHours = $("mrHours").value.trim();
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
    operating_hours: operatingHours || null,
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

async function openResourceDetails(id) {
  try {
    const resource = await api.get(`/resources/${id}`);
    $("modalRoot").innerHTML = `
      <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
        <div class="modal card inventory-detail-modal">
          <div class="modal-head"><div><h2>${esc(resource.resource_name)}</h2><p class="muted">${esc(resource.resource_code)} · ${esc(resource.category_name || "General")}</p></div><button class="btn icon" type="button" onclick="closeModal()">✕</button></div>
          <div class="modal-body">
            <div class="inventory-detail-grid">
              <div><span>Location</span><strong>${esc(resource.location || "—")}</strong></div>
              <div><span>Capacity</span><strong>${resource.capacity || "Not specified"}</strong></div>
              <div><span>Operating hours</span><strong>${esc(resource.operating_hours || "Not specified")}</strong></div>
              <div><span>Status</span><strong>${esc(resource.status)}</strong></div>
            </div>
            <p>${esc(resource.description || "No description provided.")}</p>
            <h3>Features</h3>
            <div class="meta">${(resource.features || []).map(feature => `<span class="tag">${esc(feature)}</span>`).join("") || `<span class="muted">No features listed.</span>`}</div>
            <div class="modal-foot"><button class="btn ghost" type="button" onclick="closeModal()">Close</button><button class="btn primary" type="button" onclick="closeModal();openResourceSchedule(${resource.resource_id})">View availability</button></div>
          </div>
        </div>
      </div>`;
  } catch (err) {
    toast(`Failed to load resource details: ${err.message}`, "err");
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
window.setInventoryTab = setInventoryTab;
window.renderCatalog = renderCatalog;
window.openResourceModal = openResourceModal;
window.openOperatingHoursModal = openOperatingHoursModal;
window.saveOperatingHours = saveOperatingHours;
window.filterOperatingResources = filterOperatingResources;
window.toggleAllOperatingDays = toggleAllOperatingDays;
window.syncAllOperatingDays = syncAllOperatingDays;
window.toggleOperatingExceptionHours = toggleOperatingExceptionHours;
window.createOperatingHoursException = createOperatingHoursException;
window.cancelOperatingHoursException = cancelOperatingHoursException;
window.saveResource = saveResource;
window.filterResourceInventory = filterResourceInventory;
window.filterEquipmentInventory = filterEquipmentInventory;
window.openResourceDetails = openResourceDetails;
window.quickToggleStatus = quickToggleStatus;
window.openResourceSchedule = openResourceSchedule;
window.onFilterChange = onFilterChange;
window.clearFilters = clearFilters;
