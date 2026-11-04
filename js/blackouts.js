/* =========================================================
   Smart Campus — Blackout & Maintenance Windows Module
   ========================================================= */

let blackoutsCache = [];
let blackoutResourcesCache = [];
let blackoutCategoriesCache = [];
let blackoutEquipmentCache = [];
let equipmentBlackoutsCache = [];
let blackoutEquipmentLoadError = "";
let blackoutFilters = { type: "All", q: "", categoryId: "All", dateFrom: "", dateTo: "", status: "All" };
let blackoutEditorState = null;
let blackoutSelectedCategories = new Set();
let blackoutSelectedResources = new Set();
let blackoutSelectedEquipment = new Set();
let blackoutExcludedResources = new Set();
let blackoutResourceCategoryFilter = "";
let blackoutEquipmentCategoryFilter = "All";
let blackoutSelectionMode = "resources";
let blackoutRepeatWeekdays = new Set();
const BLACKOUT_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
let blackoutPreviewSignature = "";
let blackoutPreviewData = null;
let blackoutSaveInProgress = false;

const BLACKOUT_REASONS = [
  "Maintenance",
  "University Examination",
  "College Event",
  "Holiday",
  "Cleaning",
  "Renovation",
  "Official Function",
  "Safety Restriction",
  "Other"
];

function blackoutLocalDateTime(value) {
  if (!value) return null;
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  if (match) return new Date(+match[1], +match[2] - 1, +match[3], +match[4], +match[5]);
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function blackoutInputParts(value) {
  const date = blackoutLocalDateTime(value);
  if (!date) return { date: "", time: "" };
  return {
    date: `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`,
    time: `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`
  };
}

function formatBlackoutDateTime(value) {
  const date = blackoutLocalDateTime(value);
  return date ? date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—";
}

function blackoutDateTime(date, time) {
  return date && time ? `${date}T${time}:00` : "";
}

function blackoutGroupKey(blackout) {
  return blackout.blackout_group_id || `legacy-${blackout.blackout_id}`;
}

function groupBlackouts(rows) {
  const groups = new Map();
  for (const blackout of rows) {
    const key = blackoutGroupKey(blackout);
    if (!groups.has(key)) groups.set(key, { key, rows: [], resourceNames: [], categoryIds: new Set() });
    const group = groups.get(key);
    group.rows.push(blackout);
    if (blackout.category_id) group.categoryIds.add(Number(blackout.category_id));
    for (const id of blackout.category_ids || []) group.categoryIds.add(Number(id));
  }
  return [...groups.values()].map(group => {
    group.allRows = group.rows.sort((a, b) => (a.resource_name || "").localeCompare(b.resource_name || ""));
    group.active = group.allRows.some(row => row.status === "Active");
    group.rows = group.active ? group.allRows.filter(row => row.status === "Active") : group.allRows;
    group.resourceNames = [...new Set(group.rows.map(row => row.resource_name).filter(Boolean))].sort((a, b) => a.localeCompare(b));
    group.categoryIds = new Set(group.rows.flatMap(row => [
      ...(row.category_ids || []).map(Number),
      ...(row.category_id ? [Number(row.category_id)] : [])
    ]));
    
    // Compute earliest start and latest end datetime across all occurrences in this group
    let minStart = group.rows[0].start_datetime;
    let maxEnd = group.rows[0].end_datetime;
    for (const r of group.rows) {
      if (new Date(r.start_datetime) < new Date(minStart)) minStart = r.start_datetime;
      if (new Date(r.end_datetime) > new Date(maxEnd)) maxEnd = r.end_datetime;
    }
    group.start_datetime = minStart;
    group.end_datetime = maxEnd;
    group.first = group.rows[0];
    return group;
  });
}

function blackoutCurrentState(group) {
  if (group.first.window_state) return group.first.window_state;
  if (!group.active) return "Cancelled";
  const now = Date.now();
  const start = blackoutLocalDateTime(group.start_datetime || group.first.start_datetime)?.getTime() ?? 0;
  const end = blackoutLocalDateTime(group.end_datetime || group.first.end_datetime)?.getTime() ?? 0;
  if (end < now) return "Expired";
  if (start > now) return "Upcoming";
  return "Active";
}

function blackoutResourceIsAvailable(resource) {
  return String(resource.status || "").trim().toLowerCase() === "available";
}

async function renderBlackouts() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading blackout periods...</div>`;
  $("topActions").innerHTML = `<button class="btn primary sm" type="button" onclick="openCreateBlackoutModal()">+ Add Blackout Window</button>`;

  try {
    const resourcePromise = (blackoutResourcesCache && blackoutResourcesCache.length > 0) ? Promise.resolve(blackoutResourcesCache) : api.get("/resources");
    const categoryPromise = (blackoutCategoriesCache && blackoutCategoriesCache.length > 0) ? Promise.resolve(blackoutCategoriesCache) : api.get("/categories");

    const [blackoutsRes, resourcesRes, categoriesRes, equipmentBlackoutsRes, equipmentRes] = await Promise.allSettled([
      api.get("/blackouts"),
      resourcePromise,
      categoryPromise,
      api.get("/blackouts/equipment"),
      api.get("/equipment", { is_active: "true" })
    ]);

    if (blackoutsRes.status === "fulfilled") {
      blackoutsCache = blackoutsRes.value || [];
    } else {
      throw blackoutsRes.reason || new Error("Failed to load resource blackouts.");
    }
    if (resourcesRes.status === "fulfilled") {
      blackoutResourcesCache = resourcesRes.value || [];
    }
    if (categoriesRes.status === "fulfilled") {
      blackoutCategoriesCache = categoriesRes.value || [];
    }

    const equipmentBlackouts = equipmentBlackoutsRes;
    const equipment = equipmentRes;
    const equipmentErrors = [];
    if (equipmentBlackouts.status === "fulfilled") {
      equipmentBlackoutsCache = equipmentBlackouts.value || [];
    } else {
      equipmentBlackoutsCache = [];
      equipmentErrors.push(`Equipment blackout windows: ${equipmentBlackouts.reason?.message || equipmentBlackouts.reason}`);
    }
    if (equipment.status === "fulfilled") {
      blackoutEquipmentCache = equipment.value || [];
    } else {
      blackoutEquipmentCache = [];
      equipmentErrors.push(`Equipment inventory: ${equipment.reason?.message || equipment.reason}`);
    }
    blackoutEquipmentLoadError = equipmentErrors.join(" ");
    renderBlackoutsTable();
  } catch (error) {
    host.innerHTML = `<div class="hint bad">Failed to load blackout data: ${esc(error.message)}</div>`;
  }
}

function getUnifiedBlackoutEntries() {
  const entries = [];

  // 1. Space and Resource Blackout Groups
  for (const group of groupBlackouts(blackoutsCache)) {
    const first = group.first;
    const state = blackoutCurrentState(group);
    const categories = [...new Set(group.rows.map(row => row.category_name).filter(Boolean))];
    const label = group.resourceNames.length > 1
      ? `${group.resourceNames.length} resources`
      : (group.resourceNames[0] || "Resource");
    const details = group.resourceNames.length > 1 ? group.resourceNames : [];
    const totalOccurrences = group.rows.length;
    const distinctCount = group.resourceNames.length;
    const recurrenceCount = distinctCount > 0 ? Math.round(totalOccurrences / distinctCount) : 1;
    const recurrenceNote = recurrenceCount > 1 ? `Repeats across ${recurrenceCount} days` : "";

    entries.push({
      entryType: "Resource",
      key: group.key,
      first: first,
      reasonCategory: first.reason_category || "Other",
      reasonExplanation: first.reason_explanation || first.reason || "",
      label: label,
      details: details,
      categories: categories,
      categoryIds: group.categoryIds || new Set(),
      startDatetime: group.start_datetime || first.start_datetime,
      endDatetime: group.end_datetime || first.end_datetime,
      creatorName: first.creator_name || first.created_by_name || "System",
      state: state,
      recurrenceNote: recurrenceNote,
      rawGroup: group
    });
  }

  // 2. Equipment Blackout Groups
  const eqGrouped = new Map();
  for (const blackout of equipmentBlackoutsCache) {
    const key = blackout.blackout_group_id || `equipment-${blackout.equipment_blackout_id}`;
    if (!eqGrouped.has(key)) eqGrouped.set(key, []);
    eqGrouped.get(key).push(blackout);
  }

  for (const [key, rows] of eqGrouped.entries()) {
    const first = rows[0];
    const state = first.window_state || "Upcoming";
    const itemNames = [...new Set(rows.map(r => r.item_name).filter(Boolean))].sort((a, b) => a.localeCompare(b));
    const label = itemNames.length > 1 ? `${itemNames.length} equipment items` : (itemNames[0] || "Equipment");
    const details = itemNames.length > 1 ? itemNames : [];
    const categories = [...new Set(rows.map(row => row.category).filter(Boolean))];

    let minStart = rows[0].start_datetime;
    let maxEnd = rows[0].end_datetime;
    for (const r of rows) {
      if (new Date(r.start_datetime) < new Date(minStart)) minStart = r.start_datetime;
      if (new Date(r.end_datetime) > new Date(maxEnd)) maxEnd = r.end_datetime;
    }
    const distinctEqCount = itemNames.length;
    const eqRecurrenceCount = distinctEqCount > 0 ? Math.round(rows.length / distinctEqCount) : 1;
    const recurrenceNote = eqRecurrenceCount > 1 ? `Repeats across ${eqRecurrenceCount} days` : "";

    entries.push({
      entryType: "Equipment",
      key: key,
      first: first,
      reasonCategory: first.reason_category || "Other",
      reasonExplanation: first.reason_explanation || "",
      label: label,
      details: details,
      categories: categories,
      categoryIds: new Set(),
      startDatetime: minStart,
      endDatetime: maxEnd,
      creatorName: first.creator_name || "System",
      state: state,
      recurrenceNote: recurrenceNote,
      rawRows: rows
    });
  }

  // Sort newest first by start datetime
  entries.sort((a, b) => {
    const da = blackoutLocalDateTime(a.startDatetime)?.getTime() ?? 0;
    const db = blackoutLocalDateTime(b.startDatetime)?.getTime() ?? 0;
    return db - da;
  });

  return entries;
}

function renderBlackoutsTable() {
  const host = $("view");
  const allEntries = getUnifiedBlackoutEntries();

  const filtered = allEntries.filter(entry => {
    // Filter by type (Spaces vs Equipment)
    if (blackoutFilters.type && blackoutFilters.type !== "All" && entry.entryType !== blackoutFilters.type) {
      return false;
    }

    // Filter by search query
    const query = blackoutFilters.q.trim().toLowerCase();
    if (query) {
      const searchable = [
        entry.entryType,
        entry.reasonCategory,
        entry.reasonExplanation,
        entry.label,
        ...entry.details,
        ...entry.categories
      ].join(" ").toLowerCase();
      if (!searchable.includes(query)) return false;
    }

    // Filter by category
    if (blackoutFilters.categoryId !== "All") {
      const catVal = String(blackoutFilters.categoryId);
      const matchesId = entry.categoryIds && entry.categoryIds.has(Number(catVal));
      const catObj = blackoutCategoriesCache.find(c => String(c.category_id) === catVal);
      const targetCatName = (catObj ? catObj.category_name : catVal).toLowerCase();
      const matchesName = entry.categories.some(c => c.toLowerCase() === targetCatName);
      if (!matchesId && !matchesName) return false;
    }

    // Filter by date range
    if (blackoutFilters.dateFrom &&
        blackoutLocalDateTime(entry.endDatetime) < new Date(`${blackoutFilters.dateFrom}T00:00:00`)) {
      return false;
    }
    if (blackoutFilters.dateTo &&
        blackoutLocalDateTime(entry.startDatetime) >= new Date(`${blackoutFilters.dateTo}T23:59:59`)) {
      return false;
    }

    // Filter by status
    if (blackoutFilters.status !== "All" && entry.state !== blackoutFilters.status) {
      return false;
    }

    return true;
  });

  const categoryOptions = blackoutCategoriesCache.map(category =>
    `<option value="${category.category_id}" ${String(category.category_id) === blackoutFilters.categoryId ? "selected" : ""}>${esc(category.category_name)}</option>`
  ).join("");
  const equipmentWarning = blackoutEquipmentLoadError
    ? `<div class="hint bad blackout-load-warning" role="status">Equipment options could not be loaded: ${esc(blackoutEquipmentLoadError)} Space and resource blackout options are still available. <button class="btn ghost sm" type="button" onclick="renderBlackouts()">Retry</button></div>`
    : "";

  host.innerHTML = `
    <section class="blackout-toolbar card">
      <input class="input sm" type="search" placeholder="Search resources, equipment, reasons..." aria-label="Search blackout windows"
        value="${esc(blackoutFilters.q)}" onchange="setBlackoutFilter('q', this.value)">
      <select class="input sm" aria-label="Filter by type" onchange="setBlackoutFilter('type', this.value)">
        <option value="All" ${blackoutFilters.type === "All" ? "selected" : ""}>All types</option>
        <option value="Resource" ${blackoutFilters.type === "Resource" ? "selected" : ""}>Spaces & Rooms</option>
        <option value="Equipment" ${blackoutFilters.type === "Equipment" ? "selected" : ""}>Equipment</option>
      </select>
      <select class="input sm" aria-label="Filter by category" onchange="setBlackoutFilter('categoryId', this.value)">
        <option value="All">All categories</option>${categoryOptions}
      </select>
      <input class="input sm" type="date" aria-label="Filter from date" value="${esc(blackoutFilters.dateFrom)}"
        onchange="setBlackoutFilter('dateFrom', this.value)">
      <input class="input sm" type="date" aria-label="Filter to date" value="${esc(blackoutFilters.dateTo)}"
        onchange="setBlackoutFilter('dateTo', this.value)">
      <select class="input sm" aria-label="Filter by blackout status" onchange="setBlackoutFilter('status', this.value)">
        ${["Active", "Upcoming", "Expired", "Cancelled", "All"].map(value =>
          `<option ${blackoutFilters.status === value ? "selected" : ""}>${value}</option>`).join("")}
      </select>
      <button class="btn ghost sm" type="button" onclick="clearBlackoutFilters()">Clear filters</button>
      <span class="muted">${filtered.length} blackout window(s)</span>
    </section>
    ${equipmentWarning}
    <section class="card blackout-table-card">
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Reason</th>
              <th>Type</th>
              <th>Resources / Equipment</th>
              <th>Categories</th>
              <th>Start</th>
              <th>End</th>
              <th>Created By</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>${filtered.length ? filtered.map(renderUnifiedBlackoutRow).join("") :
            `<tr><td colspan="9" class="empty">No blackout windows match these filters.</td></tr>`}</tbody>
        </table>
      </div>
    </section>`;
}

function renderUnifiedBlackoutRow(entry) {
  const state = entry.state;
  const statusClass = state === "Active" ? "bad" : state === "Upcoming" ? "warn" : state === "Cancelled" ? "info" : "muted";
  const typePill = entry.entryType === "Equipment"
    ? `<span class="pill warn" style="font-size:10.5px; padding:2px 7px;">Equipment</span>`
    : `<span class="pill info" style="font-size:10.5px; padding:2px 7px;">Space</span>`;

  const detailsHtml = entry.details.length > 0
    ? `<details class="blackout-resource-details" style="margin-top:4px;"><summary style="font-size:11.5px; cursor:pointer;">View items (${entry.details.length})</summary><ul style="margin:4px 0 0 16px; padding:0; font-size:11.5px;">${entry.details.map(name => `<li>${esc(name)}</li>`).join("")}</ul></details>`
    : "";

  let actions = [];
  if (entry.entryType === "Resource") {
    const group = entry.rawGroup;
    actions.push(`<button class="btn ghost sm" type="button" onclick="viewBlackoutDetails('${esc(entry.key)}')">Details</button>`);
    if (group.active && entry.first.maintenance_id == null) {
      actions.push(`<button class="btn ghost sm" type="button" onclick="editBlackoutGroup('${esc(entry.key)}')">Edit</button>`);
      actions.push(`<button class="btn bad sm" type="button" onclick="cancelBlackoutRecord(${entry.first.blackout_id})">Cancel</button>`);
    }
  } else {
    if (state !== "Cancelled" && state !== "Expired") {
      actions.push(`<button class="btn bad sm" type="button" onclick="cancelEquipmentBlackout(${entry.first.equipment_blackout_id})">Cancel</button>`);
    }
  }

  return `<tr>
    <td><b>${esc(entry.reasonCategory)}</b><div class="muted">${esc(entry.reasonExplanation)}</div></td>
    <td>${typePill}</td>
    <td><span style="font-weight:600;">${esc(entry.label)}</span>${detailsHtml}</td>
    <td>${esc(entry.categories.join(", ") || "—")}</td>
    <td>${formatBlackoutDateTime(entry.startDatetime)}</td>
    <td>${formatBlackoutDateTime(entry.endDatetime)}${entry.recurrenceNote ? `<div class="muted" style="font-size:11px; margin-top:2px;">${esc(entry.recurrenceNote)}</div>` : ""}</td>
    <td>${esc(entry.creatorName)}</td>
    <td><span class="pill ${statusClass}">${esc(state)}</span></td>
    <td><div class="actions">${actions.join("")}</div></td>
  </tr>`;
}

function renderBlackoutRow(group) {
  return "";
}

function renderEquipmentBlackoutGroups() {
  return "";
}

function getBlackoutGroup(key) {
  return groupBlackouts(blackoutsCache).find(group => group.key === key);
}

function viewBlackoutDetails(groupKey) {
  const group = getBlackoutGroup(groupKey);
  if (!group) return;
  const first = group.first;
  $("modalRoot").innerHTML = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <section class="modal card blackout-details-modal" role="dialog" aria-modal="true">
        <header class="panel-head"><div><h3>Blackout details</h3><p class="muted">${group.resourceNames.length} affected resource(s)</p></div>
          <button class="btn icon" type="button" aria-label="Close" onclick="closeModal()">✕</button></header>
        <p><b>${esc(first.reason_category || "Other")}</b> — ${esc(first.reason_explanation || first.reason || "")}</p>
        <p class="muted">${formatBlackoutDateTime(first.start_datetime)} – ${formatBlackoutDateTime(first.end_datetime)}</p>
        <div class="blackout-selected-list">${group.rows.map(row =>
          `<div class="blackout-selected-item"><b>${esc(row.resource_name)}</b><span>${esc(row.category_name || "Uncategorized")}</span></div>`
        ).join("")}</div>
        <p class="muted">Created by ${esc(first.creator_name || "System")} · ${fmtShort(first.created_at)}</p>
        <div class="actions blackout-modal-actions"><button class="btn ghost sm" type="button" onclick="closeModal()">Close</button></div>
      </section>
    </div>`;
}

function setBlackoutFilter(name, value) {
  const next = { ...blackoutFilters, [name]: value };
  if (next.dateFrom && next.dateTo && next.dateFrom > next.dateTo) {
    toast("The filter start date must be on or before its end date.", "err");
    return;
  }
  blackoutFilters[name] = value;
  renderBlackoutsTable();
}

function clearBlackoutFilters() {
  blackoutFilters = { type: "All", q: "", categoryId: "All", dateFrom: "", dateTo: "", status: "All" };
  renderBlackoutsTable();
}

function initBlackoutSelection(group = null) {
  blackoutEditorState = group ? { blackoutId: group.first.blackout_id, groupKey: group.key } : null;
  blackoutSelectionMode = "resources";
  blackoutRepeatWeekdays = new Set();
  blackoutSelectedCategories = new Set((group?.first.category_ids || []).map(Number));
  blackoutSelectedResources = new Set();
  blackoutSelectedEquipment = new Set();
  blackoutExcludedResources = new Set((group?.first.excluded_resource_ids || []).map(Number));
  const categoryIds = blackoutSelectedCategories;
  for (const row of group?.rows || []) {
    if (!categoryIds.has(Number(row.category_id))) blackoutSelectedResources.add(Number(row.resource_id));
  }
  blackoutPreviewSignature = "";
  blackoutPreviewData = null;
}

function openCreateBlackoutModal() {
  initBlackoutSelection();
  renderBlackoutModal();
}

function editBlackoutGroup(groupKey) {
  const group = getBlackoutGroup(groupKey);
  if (!group) return;
  initBlackoutSelection(group);
  renderBlackoutModal(group);
}

function renderBlackoutModal(group = null) {
  const first = group?.first;
  const now = new Date();
  const later = new Date(now.getTime() + 4 * 60 * 60 * 1000);
  const start = blackoutInputParts(first?.start_datetime || now);
  const end = blackoutInputParts(first?.end_datetime || later);
  const categories = blackoutCategoriesCache.map(category => {
    const count = blackoutResourcesCache.filter(resource =>
      Number(resource.category_id) === Number(category.category_id) && blackoutResourceIsAvailable(resource)
    ).length;
    return `<label class="blackout-category-option">
      <input type="checkbox" value="${category.category_id}" ${blackoutSelectedCategories.has(Number(category.category_id)) ? "checked" : ""}
        onchange="toggleBlackoutCategory(${category.category_id}, this.checked)">
      <span class="blackout-category-name">${esc(category.category_name)}</span>
      <small>${count} resource${count === 1 ? "" : "s"}</small>
    </label>`;
  }).join("");
  const reasonOptions = BLACKOUT_REASONS.map(reason =>
    `<option ${first?.reason_category === reason ? "selected" : ""}>${esc(reason)}</option>`
  ).join("");
  const equipmentCategories = [...new Set(blackoutEquipmentCache.map(item => item.category).filter(Boolean))].sort();
  const equipmentCategoryOptions = equipmentCategories.map(category =>
    `<option ${category === blackoutEquipmentCategoryFilter ? "selected" : ""}>${esc(category)}</option>`
  ).join("");
  const weekdayOptions = BLACKOUT_WEEKDAYS.map((day, index) =>
    `<label><input type="checkbox" value="${index}" ${blackoutRepeatWeekdays.has(index) ? "checked" : ""}
      onchange="setBlackoutRepeatWeekday(${index}, this.checked)">${day.slice(0, 3)}</label>`
  ).join("");

  $("modalRoot").innerHTML = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <section class="modal card blackout-editor-modal" role="dialog" aria-modal="true" aria-labelledby="blackoutEditorTitle">
        <header class="panel-head blackout-editor-header"><div><h3 id="blackoutEditorTitle">${group ? "Edit Blackout Window" : "Schedule Blackout Window"}</h3>
          <p class="muted">Select spaces or equipment, and optionally repeat the blackout on selected weekdays.</p></div>
          <button class="btn icon" type="button" aria-label="Close" onclick="closeModal()">✕</button></header>
        <div class="blackout-editor-grid">
          <section class="blackout-editor-section blackout-selection-section">
            <h4>Resource selection</h4>
            <div class="blackout-choice-mode" role="group" aria-label="Choose what to block">
              <button class="btn sm ${blackoutSelectionMode === "resources" ? "primary" : "ghost"}" type="button"
                aria-pressed="${blackoutSelectionMode === "resources"}" onclick="setBlackoutSelectionMode('resources')">Spaces</button>
              <button class="btn sm ${blackoutSelectionMode === "equipment" ? "primary" : "ghost"}" type="button"
                aria-pressed="${blackoutSelectionMode === "equipment"}" onclick="setBlackoutSelectionMode('equipment')"
                ${group || blackoutEquipmentLoadError ? "disabled" : ""} title="${blackoutEquipmentLoadError ? esc(blackoutEquipmentLoadError) : ""}">Equipment</button>
            </div>
            <div id="blackoutResourcePanel" ${blackoutSelectionMode !== "resources" ? "hidden" : ""}>
              <p class="blackout-selection-help muted">Choose categories, individual resources, or combine both.</p>
              <div class="blackout-selection-label">Select by category</div>
              <div class="blackout-category-list">${categories || `<span class="muted">No resource categories found.</span>`}</div>
              <div class="blackout-selection-label">Select individual resources</div>
              <div class="blackout-resource-controls">
                <div class="blackout-resource-search-row">
                  <input id="blackoutResourceSearch" class="input sm" type="search" aria-label="Search resources" placeholder="Search resources..." oninput="renderBlackoutResourceChoices()">
                  <select id="blackoutResourceCategoryFilter" class="input sm" aria-label="Filter resources by category" onchange="setBlackoutResourceCategoryFilter(this.value)">
                    <option value="">All categories</option>${blackoutCategoriesCache.map(category =>
                      `<option value="${category.category_id}" ${String(category.category_id) === blackoutResourceCategoryFilter ? "selected" : ""}>${esc(category.category_name)}</option>`
                    ).join("")}
                  </select>
                </div>
                <div class="blackout-resource-actions">
                  <button class="btn ghost sm" type="button" onclick="selectAllBlackoutResources()">Select all</button>
                  <button class="btn ghost sm" type="button" onclick="clearBlackoutSelection()">Clear selection</button>
                </div>
              </div>
              <details class="blackout-resource-browser">
                <summary>Browse individual resources <span id="blackoutResourceResultCount" class="muted"></span></summary>
                <div id="blackoutResourceChoices" class="blackout-resource-choices"></div>
              </details>
              <div class="blackout-selection-summary">
                <div><b id="blackoutSelectedCount">0 resources selected</b><span id="blackoutSelectedCategories" class="muted"></span></div>
                <details class="blackout-selected-details">
                  <summary>View selected resources</summary>
                  <div id="blackoutSelectedResources" class="blackout-selected-list"></div>
                </details>
              </div>
            </div>
            <div id="blackoutEquipmentPanel" ${blackoutSelectionMode !== "equipment" ? "hidden" : ""}>
              <p class="blackout-selection-help muted">Select inventory items to make their available quantity unavailable.</p>
              <div class="blackout-resource-controls">
                <div class="blackout-resource-search-row">
                  <input id="blackoutEquipmentSearch" class="input sm" type="search" aria-label="Search equipment" placeholder="Search equipment..." oninput="renderBlackoutEquipmentChoices()">
                  <select id="blackoutEquipmentCategoryFilter" class="input sm" aria-label="Filter equipment by category" onchange="setBlackoutEquipmentCategoryFilter(this.value)">
                    <option>All categories</option>${equipmentCategoryOptions}
                  </select>
                </div>
                <div class="blackout-resource-actions">
                  <button class="btn ghost sm" type="button" onclick="selectAllBlackoutEquipment()">Select all</button>
                  <button class="btn ghost sm" type="button" onclick="clearBlackoutEquipmentSelection()">Clear selection</button>
                </div>
              </div>
              <details class="blackout-resource-browser">
                <summary>Browse equipment <span id="blackoutEquipmentResultCount" class="muted"></span></summary>
                <div id="blackoutEquipmentChoices" class="blackout-resource-choices"></div>
              </details>
              <div class="blackout-selection-summary">
                <div><b id="blackoutEquipmentSelectedCount">0 equipment items selected</b></div>
                <details class="blackout-selected-details">
                  <summary>View selected equipment</summary>
                  <div id="blackoutSelectedEquipment" class="blackout-selected-list"></div>
                </details>
              </div>
            </div>
          </section>
          <section class="blackout-editor-section blackout-config-section">
            <h4>Date and time</h4>
            <div class="blackout-date-grid">
              <label>Start date<input id="blackoutStartDate" class="input sm" type="date" value="${start.date}" onchange="invalidateBlackoutPreview()"></label>
              <label>Start time<input id="blackoutStartTime" class="input sm" type="time" value="${start.time}" onchange="invalidateBlackoutPreview()"></label>
              <label>End date<input id="blackoutEndDate" class="input sm" type="date" value="${end.date}" onchange="invalidateBlackoutPreview()"></label>
              <label>End time<input id="blackoutEndTime" class="input sm" type="time" value="${end.time}" onchange="invalidateBlackoutPreview()"></label>
            </div>
            <fieldset class="blackout-repeat-field">
              <legend>Repeat on weekdays within the selected date range</legend>
              <div class="blackout-repeat-presets">
                <button class="btn ghost sm" type="button" onclick="setBlackoutWeekdays([0,1,2,3,4])">Weekdays (Mon-Fri)</button>
                <button class="btn ghost sm" type="button" onclick="setBlackoutWeekdays([])">One-time blackout</button>
              </div>
              <div class="blackout-weekday-options">${weekdayOptions}</div>
            </fieldset>
            <h4 class="blackout-subheading">Reason for Unavailability <span class="required">*</span></h4>
            <label class="field-label">Reason category<select id="blackoutReasonCategory" class="input sm" onchange="invalidateBlackoutPreview()">${reasonOptions}</select></label>
            <label class="field-label">Explanation<textarea id="blackoutReasonExplanation" class="input" rows="3" maxlength="2000"
              placeholder="Explain why these resources are unavailable." oninput="invalidateBlackoutPreview()">${esc(first?.reason_explanation || first?.reason || "")}</textarea></label>
            <div class="blackout-conflict-preview">
              <div class="blackout-conflict-heading"><b>Conflict review</b><span id="blackoutPreviewSummary" class="muted">Review existing bookings before saving.</span></div>
              <div id="blackoutConflictList"></div>
            </div>
          </section>
        </div>
        <footer class="actions blackout-editor-actions">
          <b id="blackoutFooterCount" class="blackout-footer-count">0 resources selected</b>
          <div class="blackout-footer-buttons">
          <button class="btn ghost sm" type="button" onclick="closeModal()">Cancel</button>
          <button id="blackoutReviewButton" class="btn ghost sm" type="button" onclick="reviewBlackoutConflicts()">Review conflicts</button>
          <button id="blackoutSaveButton" class="btn primary sm" type="button" onclick="submitCreateBlackout()">${group ? "Save Changes" : "Save Blackout"}</button>
          </div>
        </footer>
      </section>
    </div>`;
  renderBlackoutResourceChoices();
  renderBlackoutSelectedResources();
  renderBlackoutEquipmentChoices();
  renderBlackoutSelectedEquipment();
  updateBlackoutSelectionMode();
  updateBlackoutSaveState();
}

function updateBlackoutSelectionMode() {
  const resources = $("blackoutResourcePanel");
  const equipment = $("blackoutEquipmentPanel");
  if (resources) resources.hidden = blackoutSelectionMode !== "resources";
  if (equipment) equipment.hidden = blackoutSelectionMode !== "equipment";
  document.querySelectorAll(".blackout-choice-mode button").forEach(button => {
    const active = (button.textContent.trim() === "Equipment") === (blackoutSelectionMode === "equipment");
    button.classList.toggle("primary", active);
    button.classList.toggle("ghost", !active);
    button.setAttribute("aria-pressed", String(active));
  });
  updateBlackoutFooterCount();
}

function setBlackoutSelectionMode(mode) {
  if (blackoutEditorState?.blackoutId && mode !== "resources") return;
  blackoutSelectionMode = mode === "equipment" ? "equipment" : "resources";
  invalidateBlackoutPreview();
  updateBlackoutSelectionMode();
  renderBlackoutSelectedResources();
  renderBlackoutSelectedEquipment();
}

function renderBlackoutEquipmentChoices() {
  const container = $("blackoutEquipmentChoices");
  if (!container) return;
  const query = ($("blackoutEquipmentSearch")?.value || "").trim().toLowerCase();
  const category = $("blackoutEquipmentCategoryFilter")?.value || blackoutEquipmentCategoryFilter;
  const items = blackoutEquipmentCache.filter(item => {
    if (item.is_active === false || item.is_active === 0) return false;
    if (category && category !== "All categories" && item.category !== category) return false;
    if (query && !`${item.item_name} ${item.item_code || ""} ${item.category || ""}`.toLowerCase().includes(query)) return false;
    return true;
  });
  const resultCount = $("blackoutEquipmentResultCount");
  if (resultCount) resultCount.textContent = `${items.length} active`;
  container.innerHTML = items.length ? items.map(item =>
    `<label class="blackout-resource-option">
      <input type="checkbox" value="${item.item_id}" ${blackoutSelectedEquipment.has(Number(item.item_id)) ? "checked" : ""}
        onchange="toggleBlackoutEquipmentItem(${item.item_id}, this.checked)">
      <span><b>${esc(item.item_name)}</b><small>${esc(item.category || "Uncategorized")} · ${esc(item.item_code || "")} · ${Number(item.total_quantity || 0)} units</small></span>
    </label>`
  ).join("") : `<div class="muted">No equipment items match this search.</div>`;
}

function setBlackoutEquipmentCategoryFilter(category) {
  blackoutEquipmentCategoryFilter = category;
  renderBlackoutEquipmentChoices();
}

function toggleBlackoutEquipmentItem(itemId, selected) {
  const id = Number(itemId);
  if (selected) blackoutSelectedEquipment.add(id);
  else blackoutSelectedEquipment.delete(id);
  invalidateBlackoutPreview();
  renderBlackoutEquipmentChoices();
  renderBlackoutSelectedEquipment();
}

function selectAllBlackoutEquipment() {
  for (const item of blackoutEquipmentCache) {
    if (item.is_active !== false && item.is_active !== 0) blackoutSelectedEquipment.add(Number(item.item_id));
  }
  invalidateBlackoutPreview();
  renderBlackoutEquipmentChoices();
  renderBlackoutSelectedEquipment();
}

function clearBlackoutEquipmentSelection() {
  blackoutSelectedEquipment.clear();
  invalidateBlackoutPreview();
  renderBlackoutEquipmentChoices();
  renderBlackoutSelectedEquipment();
}

function renderBlackoutSelectedEquipment() {
  const list = $("blackoutSelectedEquipment");
  if (!list) return;
  const ids = [...blackoutSelectedEquipment].sort((a, b) => a - b);
  const count = $("blackoutEquipmentSelectedCount");
  if (count) count.textContent = `${ids.length} equipment item${ids.length === 1 ? "" : "s"} selected`;
  const details = list.closest(".blackout-selected-details");
  if (details) details.hidden = ids.length === 0;
  list.innerHTML = ids.map(id => {
    const item = blackoutEquipmentCache.find(row => Number(row.item_id) === id);
    return item ? `<span class="blackout-selected-chip">${esc(item.item_name)}
      <button type="button" aria-label="Remove ${esc(item.item_name)}" onclick="toggleBlackoutEquipmentItem(${id}, false)">×</button></span>` : "";
  }).join("") || `<span class="muted">No equipment selected.</span>`;
  updateBlackoutFooterCount();
  updateBlackoutSaveState();
}

function setBlackoutWeekdays(days) {
  blackoutRepeatWeekdays = new Set(days);
  renderBlackoutWeekdayOptions();
  invalidateBlackoutPreview();
}

function setBlackoutRepeatWeekday(day, selected) {
  if (selected) blackoutRepeatWeekdays.add(day);
  else blackoutRepeatWeekdays.delete(day);
  renderBlackoutWeekdayOptions();
  invalidateBlackoutPreview();
}

function renderBlackoutWeekdayOptions() {
  const container = document.querySelector(".blackout-weekday-options");
  if (!container) return;
  container.innerHTML = BLACKOUT_WEEKDAYS.map((day, index) =>
    `<label><input type="checkbox" value="${index}" ${blackoutRepeatWeekdays.has(index) ? "checked" : ""}
      onchange="setBlackoutRepeatWeekday(${index}, this.checked)">${day.slice(0, 3)}</label>`
  ).join("");
}

function toggleBlackoutCategory(categoryId, selected) {
  if (selected) {
    blackoutSelectedCategories.add(Number(categoryId));
    for (const resource of blackoutResourcesCache) {
      if (Number(resource.category_id) === Number(categoryId)) blackoutExcludedResources.delete(Number(resource.resource_id));
    }
  } else {
    blackoutSelectedCategories.delete(Number(categoryId));
  }
  invalidateBlackoutPreview();
  renderBlackoutResourceChoices();
  renderBlackoutSelectedResources();
}

function isBlackoutResourceSelected(resource) {
  const id = Number(resource.resource_id);
  return blackoutSelectedResources.has(id) ||
    (blackoutSelectedCategories.has(Number(resource.category_id)) && !blackoutExcludedResources.has(id));
}

function toggleBlackoutResource(resourceId, selected) {
  const resource = blackoutResourcesCache.find(row => Number(row.resource_id) === Number(resourceId));
  if (!resource) return;
  const id = Number(resourceId);
  if (selected) {
    blackoutSelectedResources.add(id);
    blackoutExcludedResources.delete(id);
  } else {
    blackoutSelectedResources.delete(id);
    if (blackoutSelectedCategories.has(Number(resource.category_id))) blackoutExcludedResources.add(id);
  }
  invalidateBlackoutPreview();
  renderBlackoutResourceChoices();
  renderBlackoutSelectedResources();
}

function renderBlackoutResourceChoices() {
  const container = $("blackoutResourceChoices");
  if (!container) return;
  const query = ($("blackoutResourceSearch")?.value || "").trim().toLowerCase();
  const resources = blackoutResourcesCache.filter(resource => {
    if (!blackoutResourceIsAvailable(resource)) return false;
    if (blackoutResourceCategoryFilter && String(resource.category_id) !== blackoutResourceCategoryFilter) return false;
    if (query && !`${resource.resource_name} ${resource.resource_code || ""} ${resource.category_name || ""}`.toLowerCase().includes(query)) return false;
    return true;
  });
  const resultCount = $("blackoutResourceResultCount");
  if (resultCount) resultCount.textContent = `${resources.length} available`;
  container.innerHTML = resources.length ? resources.map(resource =>
    `<label class="blackout-resource-option">
      <input type="checkbox" value="${resource.resource_id}" ${isBlackoutResourceSelected(resource) ? "checked" : ""}
        onchange="toggleBlackoutResource(${resource.resource_id}, this.checked)">
      <span><b>${esc(resource.resource_name)}</b><small>${esc(resource.category_name || "Uncategorized")} · ${esc(resource.location || "")}</small></span>
    </label>`
  ).join("") : `<div class="muted">No available resources match this search.</div>`;
}

function setBlackoutResourceCategoryFilter(categoryId) {
  blackoutResourceCategoryFilter = categoryId;
  renderBlackoutResourceChoices();
}

function getSelectedBlackoutResources() {
  const selected = new Set(blackoutSelectedResources);
  for (const resource of blackoutResourcesCache) {
    const id = Number(resource.resource_id);
    if (blackoutSelectedCategories.has(Number(resource.category_id)) && !blackoutExcludedResources.has(id)) selected.add(id);
  }
  return [...selected].sort((a, b) => a - b);
}

function renderBlackoutSelectedResources() {
  const list = $("blackoutSelectedResources");
  if (!list) return;
  const ids = getSelectedBlackoutResources();
  const countLabel = `${ids.length} resource${ids.length === 1 ? "" : "s"} selected`;
  $("blackoutSelectedCount").textContent = countLabel;
  updateBlackoutFooterCount();
  const selectedCategoryNames = blackoutCategoriesCache
    .filter(category => blackoutSelectedCategories.has(Number(category.category_id)))
    .map(category => category.category_name);
  $("blackoutSelectedCategories").textContent = selectedCategoryNames.length
    ? `Selected categories: ${selectedCategoryNames.join(", ")}`
    : "Selected categories: none";
  const selectedDetails = list.closest(".blackout-selected-details");
  if (selectedDetails) selectedDetails.hidden = ids.length === 0;
  list.innerHTML = ids.map(id => {
    const resource = blackoutResourcesCache.find(row => Number(row.resource_id) === id);
    if (!resource) return "";
    return `<span class="blackout-selected-chip">${esc(resource.resource_name)}
      <button type="button" aria-label="Remove ${esc(resource.resource_name)}" onclick="toggleBlackoutResource(${id}, false)">×</button></span>`;
  }).join("") || `<span class="muted">No resources selected.</span>`;
  updateBlackoutSaveState();
}

function updateBlackoutFooterCount() {
  const footerCount = $("blackoutFooterCount");
  if (!footerCount) return;
  if (blackoutSelectionMode === "equipment") {
    const count = blackoutSelectedEquipment.size;
    footerCount.textContent = `${count} equipment item${count === 1 ? "" : "s"} selected`;
  } else {
    const count = getSelectedBlackoutResources().length;
    footerCount.textContent = `${count} resource${count === 1 ? "" : "s"} selected`;
  }
}

function selectAllBlackoutResources() {
  for (const resource of blackoutResourcesCache) {
    if (blackoutResourceIsAvailable(resource)) blackoutSelectedResources.add(Number(resource.resource_id));
  }
  blackoutExcludedResources.clear();
  invalidateBlackoutPreview();
  renderBlackoutResourceChoices();
  renderBlackoutSelectedResources();
}

function clearBlackoutSelection() {
  blackoutSelectedCategories.clear();
  blackoutSelectedResources.clear();
  blackoutExcludedResources.clear();
  invalidateBlackoutPreview();
  document.querySelectorAll(".blackout-category-list input").forEach(input => { input.checked = false; });
  renderBlackoutResourceChoices();
  renderBlackoutSelectedResources();
}

function blackoutFormPayload(includeReason = true) {
  const start = blackoutDateTime($("blackoutStartDate")?.value, $("blackoutStartTime")?.value);
  const end = blackoutDateTime($("blackoutEndDate")?.value, $("blackoutEndTime")?.value);
  const payload = {
    start_datetime: start,
    end_datetime: end,
    repeat_weekdays: [...blackoutRepeatWeekdays].sort((a, b) => a - b)
  };
  if (blackoutSelectionMode === "equipment") {
    payload.equipment_ids = [...blackoutSelectedEquipment].sort((a, b) => a - b);
  } else {
    payload.resource_ids = getSelectedBlackoutResources();
    payload.excluded_resource_ids = [...blackoutExcludedResources].sort((a, b) => a - b);
    payload.category_ids = [...blackoutSelectedCategories].sort((a, b) => a - b);
  }
  if (includeReason) {
    payload.reason_category = $("blackoutReasonCategory")?.value || "Other";
    payload.reason_explanation = $("blackoutReasonExplanation")?.value.trim() || "";
  }
  return payload;
}

function validateBlackoutForm(includeReason = true) {
  const payload = blackoutFormPayload(includeReason);
  if (blackoutSelectionMode === "equipment" ? !payload.equipment_ids.length : !payload.resource_ids.length) {
    return blackoutSelectionMode === "equipment"
      ? "Select at least one equipment item."
      : "Select at least one resource or category.";
  }
  if (!payload.start_datetime || !payload.end_datetime) return "Specify a start and end date and time.";
  if (payload.repeat_weekdays.length) {
    if ($("blackoutEndDate").value < $("blackoutStartDate").value) {
      return "Repeat end date must be on or after the start date.";
    }
    if ($("blackoutEndTime").value <= $("blackoutStartTime").value) {
      return "For weekday repeats, end time must be later than start time.";
    }
  } else if (new Date(payload.end_datetime) <= new Date(payload.start_datetime)) {
    return "End date and time must be later than the start.";
  }
  if (includeReason && !payload.reason_explanation) return "Enter the reason for unavailability.";
  return "";
}

function blackoutSignature(payload) {
  return JSON.stringify(payload);
}

function invalidateBlackoutPreview() {
  blackoutPreviewSignature = "";
  blackoutPreviewData = null;
  const summary = $("blackoutPreviewSummary");
  const list = $("blackoutConflictList");
  const save = $("blackoutSaveButton");
  if (summary) summary.textContent = "Review existing bookings before saving.";
  if (list) list.innerHTML = "";
  if (save) {
    save.textContent = blackoutEditorState?.blackoutId ? "Save Changes" : "Save Blackout";
    updateBlackoutSaveState();
  }
}

function updateBlackoutSaveState() {
  const save = $("blackoutSaveButton");
  if (!save) return;
  save.disabled = blackoutSaveInProgress;
  save.setAttribute("aria-busy", String(blackoutSaveInProgress));
  const review = $("blackoutReviewButton");
  if (review) review.disabled = blackoutSaveInProgress;
}

async function reviewBlackoutConflicts() {
  const error = validateBlackoutForm(false);
  if (error) {
    toast(error, "err");
    return;
  }
  const payload = blackoutFormPayload(false);
  const signature = blackoutSignature(payload);
  const button = $("blackoutReviewButton");
  button.disabled = true;
  button.textContent = "Checking...";
  try {
    const previewPath = blackoutSelectionMode === "equipment"
      ? "/blackouts/equipment/conflicts"
      : "/blackouts/conflicts";
    blackoutPreviewData = await api.post(previewPath, payload);
    blackoutPreviewSignature = signature;
    renderBlackoutConflictPreview(blackoutPreviewData);
  } catch (err) {
    const list = $("blackoutConflictList");
    if (list) list.innerHTML = `<div class="hint error">${esc(err.message)}</div>`;
    toast(`Could not check blackout conflicts: ${err.message}`, "err");
  } finally {
    button.disabled = blackoutSaveInProgress;
    button.textContent = "Review conflicts";
  }
}

function renderBlackoutConflictPreview(preview) {
  const summary = $("blackoutPreviewSummary");
  const list = $("blackoutConflictList");
  const save = $("blackoutSaveButton");
  if (!summary || !list || !save) return;
  const conflicts = preview.conflicts || [];
  const conflictCount = Number(preview.conflict_count ?? conflicts.length);
  const affectedResources = new Set(conflicts.map(conflict => conflict.resource_id)).size;
  const affectedResourceCount = Number(preview.equipment_count || preview.resource_count || affectedResources);
  const selectedKind = blackoutSelectionMode === "equipment" ? "equipment item" : "resource";
  if (conflictCount) {
    summary.textContent = `${affectedResourceCount} ${selectedKind}${affectedResourceCount === 1 ? "" : "s"} reviewed · ` +
      `${conflictCount} overlapping booking${conflictCount === 1 ? "" : "s"} across ` +
      `${affectedResources} affected item${affectedResources === 1 ? "" : "s"}.`;
    list.innerHTML = `<div class="blackout-conflict-list">${conflicts.map(conflict =>
      `<article class="blackout-conflict">
        <b>${esc(conflict.resource_name)}</b> · ${esc(conflict.requester_name || "Requester")} · ${esc(conflict.status)}
        <span>${formatBlackoutDateTime(conflict.start_time)} – ${formatBlackoutDateTime(conflict.end_time)}</span>
        ${conflict.blackout_start_datetime ? `<small>Proposed blackout: ${formatBlackoutDateTime(conflict.blackout_start_datetime)} – ${formatBlackoutDateTime(conflict.blackout_end_datetime)}</small>` : ""}
        <small>BK-${conflict.booking_id}: ${esc(conflict.purpose || "")}</small>
      </article>`
    ).join("")}</div>`;
    save.textContent = blackoutEditorState?.blackoutId ? "Confirm Changes" : "Confirm Blackout";
  } else {
    summary.textContent = `Affected ${selectedKind}s: ${affectedResourceCount} · Overlapping bookings: 0.`;
    list.innerHTML = "";
    save.textContent = blackoutEditorState?.blackoutId ? "Save Changes" : "Save Blackout";
  }
  updateBlackoutSaveState();
}

async function submitCreateBlackout() {
  if (blackoutSaveInProgress) return;
  const error = validateBlackoutForm(true);
  if (error) {
    toast(error, "err");
    return;
  }
  blackoutSaveInProgress = true;
  updateBlackoutSaveState();
  const payload = blackoutFormPayload(true);
  const selectionPayload = blackoutFormPayload(false);
  try {
    if (blackoutPreviewSignature !== blackoutSignature(selectionPayload) || !blackoutPreviewData) {
      await reviewBlackoutConflicts();
      if (blackoutPreviewSignature !== blackoutSignature(selectionPayload) || !blackoutPreviewData) return;
      if (blackoutPreviewData.conflict_count) {
        toast("Review the overlapping bookings, then confirm to save without cancelling them.", "err");
        return;
      }
    }
    const hasConflicts = Boolean(blackoutPreviewData.conflict_count);
    if (hasConflicts && !confirm(
      `${blackoutPreviewData.conflict_count} existing pending or approved booking(s) overlap this blackout. ` +
      "Continue? Existing bookings will not be cancelled, and affected users will be notified."
    )) return;
    payload.confirm_booking_conflicts = hasConflicts;
    const saveButton = $("blackoutSaveButton");
    if (saveButton) saveButton.textContent = "Saving...";
    if (blackoutEditorState?.blackoutId) {
      await api.put(`/blackouts/${blackoutEditorState.blackoutId}`, payload);
      toast("Blackout window updated.", "ok");
    } else if (blackoutSelectionMode === "equipment") {
      const created = await api.post("/blackouts/equipment", payload);
      toast(`Equipment blackout scheduled for ${created.equipment_count} item(s) across ${created.occurrence_count} occurrence(s).`, "ok");
    } else {
      const created = await api.post("/blackouts", payload);
      toast(`Blackout scheduled for ${created.resource_count} resource(s) across ${created.occurrence_count} occurrence(s).`, "ok");
    }
    closeModal();
    await renderBlackouts();
  } catch (err) {
    let detail = null;
    try { detail = JSON.parse(err.message); } catch (_) {}
    if (detail?.conflicts) {
      renderBlackoutConflictPreview({
        conflict_count: detail.conflicts.length,
        conflicts: detail.conflicts
      });
      blackoutPreviewSignature = blackoutSignature(selectionPayload);
      blackoutPreviewData = {
        conflict_count: detail.conflicts.length,
        conflicts: detail.conflicts,
        resource_count: blackoutSelectionMode === "equipment"
          ? blackoutSelectedEquipment.size
          : getSelectedBlackoutResources().length,
        equipment_count: blackoutSelectionMode === "equipment" ? blackoutSelectedEquipment.size : undefined,
      };
      renderBlackoutConflictPreview(blackoutPreviewData);
      toast(detail.message || "Bookings now conflict with this blackout. Review and confirm again.", "err");
    } else {
      toast(detail?.message || err.message || "Failed to save blackout window.", "err");
    }
  } finally {
    blackoutSaveInProgress = false;
    const activeSaveButton = $("blackoutSaveButton");
    if (activeSaveButton) {
      activeSaveButton.textContent = blackoutPreviewData?.conflict_count
        ? (blackoutEditorState?.blackoutId ? "Confirm Changes" : "Confirm Blackout")
        : (blackoutEditorState?.blackoutId ? "Save Changes" : "Save Blackout");
    }
    updateBlackoutSaveState();
  }
}

async function cancelBlackoutRecord(blackoutId) {
  if (!confirm("Cancel this blackout window? Its history will be retained and affected resources reopened.")) return;
  try {
    await api.patch(`/blackouts/${blackoutId}/cancel`);
    toast("Blackout cancelled; history retained.", "ok");
    renderBlackouts();
  } catch (err) {
    toast(err.message || "Failed to cancel blackout.", "err");
  }
}

async function cancelEquipmentBlackout(blackoutId) {
  if (!confirm("Cancel this equipment blackout? Its history will be retained and equipment availability restored.")) return;
  try {
    await api.patch(`/blackouts/equipment/${blackoutId}/cancel`);
    toast("Equipment blackout cancelled; history retained.", "ok");
    renderBlackouts();
  } catch (err) {
    toast(err.message || "Failed to cancel equipment blackout.", "err");
  }
}

window.renderBlackouts = renderBlackouts;
window.renderBlackoutsTable = renderBlackoutsTable;
window.openCreateBlackoutModal = openCreateBlackoutModal;
window.submitCreateBlackout = submitCreateBlackout;
window.cancelBlackoutRecord = cancelBlackoutRecord;
window.setBlackoutFilter = setBlackoutFilter;
window.clearBlackoutFilters = clearBlackoutFilters;
window.viewBlackoutDetails = viewBlackoutDetails;
window.editBlackoutGroup = editBlackoutGroup;
window.toggleBlackoutCategory = toggleBlackoutCategory;
window.toggleBlackoutResource = toggleBlackoutResource;
window.renderBlackoutResourceChoices = renderBlackoutResourceChoices;
window.setBlackoutResourceCategoryFilter = setBlackoutResourceCategoryFilter;
window.selectAllBlackoutResources = selectAllBlackoutResources;
window.clearBlackoutSelection = clearBlackoutSelection;
window.invalidateBlackoutPreview = invalidateBlackoutPreview;
window.reviewBlackoutConflicts = reviewBlackoutConflicts;
window.setBlackoutSelectionMode = setBlackoutSelectionMode;
window.toggleBlackoutEquipmentItem = toggleBlackoutEquipmentItem;
window.renderBlackoutEquipmentChoices = renderBlackoutEquipmentChoices;
window.setBlackoutEquipmentCategoryFilter = setBlackoutEquipmentCategoryFilter;
window.selectAllBlackoutEquipment = selectAllBlackoutEquipment;
window.clearBlackoutEquipmentSelection = clearBlackoutEquipmentSelection;
window.setBlackoutRepeatWeekday = setBlackoutRepeatWeekday;
window.setBlackoutWeekdays = setBlackoutWeekdays;
window.cancelEquipmentBlackout = cancelEquipmentBlackout;
