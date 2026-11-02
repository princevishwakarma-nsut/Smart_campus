/* =========================================================
   Smart Campus — Blackout & Maintenance Windows Module
   ========================================================= */

let blackoutsCache = [];
let blackoutResourcesCache = [];
let blackoutCategoriesCache = [];
let blackoutFilters = { q: "", categoryId: "All", dateFrom: "", dateTo: "", status: "All" };
let blackoutEditorState = null;
let blackoutSelectedCategories = new Set();
let blackoutSelectedResources = new Set();
let blackoutExcludedResources = new Set();
let blackoutPreviewSignature = "";
let blackoutPreviewData = null;

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
    group.allRows = group.rows.sort((a, b) => a.resource_name.localeCompare(b.resource_name));
    group.active = group.allRows.some(row => row.status === "Active");
    group.rows = group.active ? group.allRows.filter(row => row.status === "Active") : group.allRows;
    group.rows.sort((a, b) => a.resource_name.localeCompare(b.resource_name));
    group.resourceNames = group.rows.map(row => row.resource_name).filter(Boolean);
    group.resourceNames.sort((a, b) => a.localeCompare(b));
    group.categoryIds = new Set(group.rows.flatMap(row => [
      ...(row.category_ids || []).map(Number),
      ...(row.category_id ? [Number(row.category_id)] : [])
    ]));
    group.first = group.rows[0];
    return group;
  });
}

function blackoutCurrentState(group) {
  if (group.first.window_state) return group.first.window_state;
  if (!group.active) return "Cancelled";
  const now = Date.now();
  const start = blackoutLocalDateTime(group.first.start_datetime)?.getTime() ?? 0;
  const end = blackoutLocalDateTime(group.first.end_datetime)?.getTime() ?? 0;
  if (end < now) return "Expired";
  if (start > now) return "Upcoming";
  return "Active";
}

async function renderBlackouts() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading blackout periods...</div>`;
  $("topActions").innerHTML = `<button class="btn primary sm" type="button" onclick="openCreateBlackoutModal()">+ Add Blackout Window</button>`;

  try {
    const [blackouts, resources, categories] = await Promise.all([
      api.get("/blackouts"),
      api.get("/resources"),
      api.get("/categories")
    ]);
    blackoutsCache = blackouts || [];
    blackoutResourcesCache = resources || [];
    blackoutCategoriesCache = categories || [];
    renderBlackoutsTable();
  } catch (error) {
    host.innerHTML = `<div class="hint error">Failed to load blackouts: ${esc(error.message)}</div>`;
  }
}

function renderBlackoutsTable() {
  const host = $("view");
  const groups = groupBlackouts(blackoutsCache).filter(group => {
    const state = blackoutCurrentState(group);
    const query = blackoutFilters.q.trim().toLowerCase();
    const searchable = [
      group.first.reason_category,
      group.first.reason_explanation || group.first.reason,
      ...group.resourceNames,
      ...group.rows.map(row => row.category_name || "")
    ].join(" ").toLowerCase();
    if (query && !searchable.includes(query)) return false;
    if (blackoutFilters.categoryId !== "All" &&
        !group.rows.some(row => String(row.category_id) === blackoutFilters.categoryId) &&
        !group.categoryIds.has(Number(blackoutFilters.categoryId))) return false;
    if (blackoutFilters.dateFrom &&
        blackoutLocalDateTime(group.first.end_datetime) < new Date(`${blackoutFilters.dateFrom}T00:00:00`)) return false;
    if (blackoutFilters.dateTo &&
        blackoutLocalDateTime(group.first.start_datetime) >= new Date(`${blackoutFilters.dateTo}T23:59:59`)) return false;
    if (blackoutFilters.status !== "All" && state !== blackoutFilters.status) return false;
    return true;
  });

  const categoryOptions = blackoutCategoriesCache.map(category =>
    `<option value="${category.category_id}" ${String(category.category_id) === blackoutFilters.categoryId ? "selected" : ""}>${esc(category.category_name)}</option>`
  ).join("");
  host.innerHTML = `
    <section class="blackout-toolbar card">
      <input class="input sm" type="search" placeholder="Search resources or blackout reasons" aria-label="Search blackout windows"
        value="${esc(blackoutFilters.q)}" onchange="setBlackoutFilter('q', this.value)">
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
      <span class="muted">${groups.length} blackout window(s)</span>
    </section>
    <section class="card blackout-table-card">
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>Reason</th><th>Resources</th><th>Categories</th><th>Start</th><th>End</th><th>Created By</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>${groups.length ? groups.map(renderBlackoutRow).join("") :
            `<tr><td colspan="8" class="empty">No blackout windows match these filters.</td></tr>`}</tbody>
        </table>
      </div>
    </section>`;
}

function renderBlackoutRow(group) {
  const first = group.first;
  const state = blackoutCurrentState(group);
  const categories = [...new Set(group.rows.map(row => row.category_name).filter(Boolean))];
  const statusClass = state === "Active" ? "bad" : state === "Upcoming" ? "warn" : state === "Cancelled" ? "info" : "muted";
  const resourceLabel = group.resourceNames.length > 1
    ? `${group.resourceNames.length} resources`
    : (group.resourceNames[0] || "Resource");
  return `<tr>
    <td><b>${esc(first.reason_category || "Other")}</b><div class="muted">${esc(first.reason_explanation || first.reason || "")}</div></td>
    <td>${esc(resourceLabel)}</td>
    <td>${esc(categories.join(", ") || "—")}</td>
    <td>${formatBlackoutDateTime(first.start_datetime)}</td><td>${formatBlackoutDateTime(first.end_datetime)}</td>
    <td>${esc(first.creator_name || "System")}</td>
    <td><span class="pill ${statusClass}">${esc(state)}</span></td>
    <td><div class="actions">
      <button class="btn ghost sm" type="button" onclick="viewBlackoutDetails('${esc(group.key)}')">Details</button>
      ${group.active && first.maintenance_id == null ? `<button class="btn ghost sm" type="button" onclick="editBlackoutGroup('${esc(group.key)}')">Edit</button>
      <button class="btn bad sm" type="button" onclick="cancelBlackoutRecord(${first.blackout_id})">Cancel</button>` : ""}
    </div></td>
  </tr>`;
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
  blackoutFilters = { q: "", categoryId: "All", dateFrom: "", dateTo: "", status: "All" };
  renderBlackoutsTable();
}

function initBlackoutSelection(group = null) {
  blackoutEditorState = group ? { blackoutId: group.first.blackout_id, groupKey: group.key } : null;
  blackoutSelectedCategories = new Set((group?.first.category_ids || []).map(Number));
  blackoutSelectedResources = new Set();
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
      Number(resource.category_id) === Number(category.category_id) && resource.status === "Available"
    ).length;
    return `<label class="blackout-category-option">
      <input type="checkbox" value="${category.category_id}" ${blackoutSelectedCategories.has(Number(category.category_id)) ? "checked" : ""}
        onchange="toggleBlackoutCategory(${category.category_id}, this.checked)">
      <span class="blackout-category-name">${esc(category.category_name)}</span><small>${count} resources</small>
    </label>`;
  }).join("");
  const reasonOptions = BLACKOUT_REASONS.map(reason =>
    `<option ${first?.reason_category === reason ? "selected" : ""}>${esc(reason)}</option>`
  ).join("");

  $("modalRoot").innerHTML = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <section class="modal card blackout-editor-modal" role="dialog" aria-modal="true" aria-labelledby="blackoutEditorTitle">
        <header class="panel-head blackout-editor-header"><div><h3 id="blackoutEditorTitle">${group ? "Edit Blackout Window" : "Schedule Blackout Window"}</h3>
          <p class="muted">Select categories, individual resources, or both in one operation.</p></div>
          <button class="btn icon" type="button" aria-label="Close" onclick="closeModal()">✕</button></header>
        <div class="blackout-editor-grid">
          <section class="blackout-editor-section blackout-selection-section">
            <h4>Resource selection</h4>
            <div class="blackout-selection-label">Select by category</div>
            <div class="blackout-category-list">${categories || `<span class="muted">No resource categories found.</span>`}</div>
            <div class="blackout-selection-label">Select individual resources</div>
            <div class="blackout-resource-controls">
              <input id="blackoutResourceSearch" class="input sm" type="search" aria-label="Search resources" placeholder="Search resources..." oninput="renderBlackoutResourceChoices()">
              <button class="btn ghost sm" type="button" onclick="selectAllBlackoutResources()">Select all</button>
              <button class="btn ghost sm" type="button" onclick="clearBlackoutSelection()">Clear selection</button>
            </div>
            <div id="blackoutResourceChoices" class="blackout-resource-choices"></div>
            <div class="blackout-selection-summary">
              <div><b id="blackoutSelectedCount">0 resources selected</b><span id="blackoutSelectedCategories" class="muted"></span></div>
              <div id="blackoutSelectedResources" class="blackout-selected-list"></div>
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
          <button id="blackoutSaveButton" class="btn primary sm" type="button" disabled onclick="submitCreateBlackout()">${group ? "Save Changes" : "Save Blackout"}</button>
          </div>
        </footer>
      </section>
    </div>`;
  renderBlackoutResourceChoices();
  renderBlackoutSelectedResources();
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
    if (resource.status !== "Available") return false;
    if (query && !`${resource.resource_name} ${resource.resource_code || ""} ${resource.category_name || ""}`.toLowerCase().includes(query)) return false;
    return true;
  });
  container.innerHTML = resources.length ? resources.map(resource =>
    `<label class="blackout-resource-option">
      <input type="checkbox" value="${resource.resource_id}" ${isBlackoutResourceSelected(resource) ? "checked" : ""}
        onchange="toggleBlackoutResource(${resource.resource_id}, this.checked)">
      <span><b>${esc(resource.resource_name)}</b><small>${esc(resource.category_name || "Uncategorized")} · ${esc(resource.location || "")}</small></span>
    </label>`
  ).join("") : `<div class="muted">No available resources match this search.</div>`;
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
  const footerCount = $("blackoutFooterCount");
  if (footerCount) footerCount.textContent = countLabel;
  const selectedCategoryNames = blackoutCategoriesCache
    .filter(category => blackoutSelectedCategories.has(Number(category.category_id)))
    .map(category => category.category_name);
  $("blackoutSelectedCategories").textContent = selectedCategoryNames.length
    ? `Selected categories: ${selectedCategoryNames.join(", ")}`
    : "Selected categories: none";
  list.innerHTML = ids.map(id => {
    const resource = blackoutResourcesCache.find(row => Number(row.resource_id) === id);
    if (!resource) return "";
    return `<span class="blackout-selected-chip">${esc(resource.resource_name)}
      <button type="button" aria-label="Remove ${esc(resource.resource_name)}" onclick="toggleBlackoutResource(${id}, false)">×</button></span>`;
  }).join("") || `<span class="muted">No resources selected.</span>`;
}

function selectAllBlackoutResources() {
  for (const resource of blackoutResourcesCache) {
    if (resource.status === "Available") blackoutSelectedResources.add(Number(resource.resource_id));
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
    resource_ids: getSelectedBlackoutResources(),
    excluded_resource_ids: [...blackoutExcludedResources].sort((a, b) => a - b),
    category_ids: [...blackoutSelectedCategories].sort((a, b) => a - b),
    start_datetime: start,
    end_datetime: end
  };
  if (includeReason) {
    payload.reason_category = $("blackoutReasonCategory")?.value || "Other";
    payload.reason_explanation = $("blackoutReasonExplanation")?.value.trim() || "";
  }
  return payload;
}

function validateBlackoutForm(includeReason = true) {
  const payload = blackoutFormPayload(includeReason);
  if (!payload.resource_ids.length) return "Select at least one resource or category.";
  if (!payload.start_datetime || !payload.end_datetime) return "Specify a start and end date and time.";
  if (new Date(payload.end_datetime) <= new Date(payload.start_datetime)) return "End date and time must be later than the start.";
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
  if (save) save.disabled = true;
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
    blackoutPreviewData = await api.post("/blackouts/conflicts", payload);
    blackoutPreviewSignature = signature;
    renderBlackoutConflictPreview(blackoutPreviewData);
  } catch (err) {
    const list = $("blackoutConflictList");
    if (list) list.innerHTML = `<div class="hint error">${esc(err.message)}</div>`;
    toast(`Could not check blackout conflicts: ${err.message}`, "err");
  } finally {
    button.disabled = false;
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
  const affectedResourceCount = Number(preview.resource_count || affectedResources);
  if (conflictCount) {
    summary.textContent = `${affectedResourceCount} resources reviewed · ${conflictCount} overlapping booking(s) across ${affectedResources} resource(s).`;
    list.innerHTML = `<div class="blackout-conflict-list">${conflicts.map(conflict =>
      `<article class="blackout-conflict">
        <b>${esc(conflict.resource_name)}</b> · ${esc(conflict.requester_name || "Requester")} · ${esc(conflict.status)}
        <span>${formatBlackoutDateTime(conflict.start_time)} – ${formatBlackoutDateTime(conflict.end_time)}</span>
        <small>BK-${conflict.booking_id}: ${esc(conflict.purpose || "")}</small>
      </article>`
    ).join("")}</div>`;
    save.disabled = true;
  } else {
    summary.textContent = `Affected resources: ${affectedResourceCount} · Overlapping bookings: 0.`;
    list.innerHTML = "";
    save.disabled = false;
  }
}

async function submitCreateBlackout() {
  const error = validateBlackoutForm(true);
  if (error) {
    toast(error, "err");
    return;
  }
  const payload = blackoutFormPayload(true);
  const selectionPayload = blackoutFormPayload(false);
  if (blackoutPreviewSignature !== blackoutSignature(selectionPayload) || !blackoutPreviewData) {
    await reviewBlackoutConflicts();
    if (blackoutPreviewSignature !== blackoutSignature(selectionPayload) ||
        !blackoutPreviewData || blackoutPreviewData.conflict_count) return;
  }
  try {
    if (blackoutEditorState?.blackoutId) {
      await api.put(`/blackouts/${blackoutEditorState.blackoutId}`, payload);
      toast("Blackout window updated.", "ok");
    } else {
      const created = await api.post("/blackouts", payload);
      toast(`Blackout scheduled for ${created.resource_count} resource(s).`, "ok");
    }
    closeModal();
    renderBlackouts();
  } catch (err) {
    let detail = null;
    try { detail = JSON.parse(err.message); } catch (_) {}
    if (detail?.conflicts) {
      renderBlackoutConflictPreview({
        conflict_count: detail.conflicts.length,
        conflicts: detail.conflicts
      });
      blackoutPreviewSignature = "";
      toast(detail.message || "Bookings now conflict with this blackout.", "err");
    } else {
      toast(err.message || "Failed to save blackout window.", "err");
    }
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
window.selectAllBlackoutResources = selectAllBlackoutResources;
window.clearBlackoutSelection = clearBlackoutSelection;
window.invalidateBlackoutPreview = invalidateBlackoutPreview;
window.reviewBlackoutConflicts = reviewBlackoutConflicts;
