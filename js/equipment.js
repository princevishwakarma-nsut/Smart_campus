/* =========================================================
   Smart Campus — Equipment Inventory & Handover Module
   ========================================================= */

function openEquipmentModal() {
  if (!isAdmin()) {
    toast("Only administrators can manage the campus inventory.", "err");
    return;
  }
  inventoryActiveTab = "equipment";
  if (state.view !== "resources") {
    go("resources");
  } else {
    renderResources();
  }
}

function openReturnEquipmentModal(itemId) {
  const itemName = liveEquipmentInventory.find(item => item.item_id === itemId)?.item_name || "Equipment";
  const root = $("modalRoot");
  root.innerHTML = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <div class="modal card" style="max-width:460px;margin:auto;">
        <h3>Return Equipment: ${esc(itemName)}</h3>
        <p class="sub">Inspect condition and restore equipment to active inventory.</p>

        <div class="field">
          <label>Booking ID (optional)</label>
          <input id="returnBookingId" class="input" type="number" min="1" placeholder="Automatically use latest active loan">
        </div>
        <div class="form-grid">
          <div class="field">
            <label>Good units returned</label>
            <input id="returnGoodQty" class="input" type="number" min="0" value="1">
          </div>
          <div class="field">
            <label>Damaged units returned</label>
            <input id="returnDamagedQty" class="input" type="number" min="0" value="0">
          </div>
          <div class="field">
            <label>Lost units</label>
            <input id="returnLostQty" class="input" type="number" min="0" value="0">
          </div>
        </div>
        <div class="field">
          <label>Condition on Return *</label>
          <select id="returnCond" class="input" onchange="setReturnConditionDefaults(this.value)">
            <option value="Good">Good</option>
            <option value="Damaged">Damaged</option>
          </select>
        </div>

        <div class="field">
          <label>Inspection Notes / Remarks</label>
          <textarea id="returnRemarks" class="input" rows="3" placeholder="Condition details, missing accessories, cables returned..."></textarea>
        </div>

        <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:20px;">
          <button class="btn ghost sm" type="button" onclick="closeModal()">Cancel</button>
          <button class="btn primary sm" type="button" onclick="submitReturnEquipment(${itemId})">Record Return</button>
        </div>
      </div>
    </div>
  `;
}

function setReturnConditionDefaults(condition) {
  if (condition === "Damaged") {
    $("returnGoodQty").value = "0";
    $("returnDamagedQty").value = "1";
  } else {
    $("returnGoodQty").value = "1";
    $("returnDamagedQty").value = "0";
  }
}

async function submitReturnEquipment(itemId) {
  const cond = $("returnCond").value;
  const remarks = $("returnRemarks").value.trim();
  const bookingId = parseInt($("returnBookingId").value, 10) || null;
  const good = parseInt($("returnGoodQty").value, 10) || 0;
  const damaged = parseInt($("returnDamagedQty").value, 10) || 0;
  const lost = parseInt($("returnLostQty").value, 10) || 0;
  if (good + damaged + lost < 1) {
    toast("Specify at least one good, damaged, or lost unit.", "err");
    return;
  }

  try {
    await api.post(`/equipment/${itemId}/return`, {
      booking_id: bookingId,
      returned_good_quantity: good,
      returned_damaged_quantity: damaged,
      lost_quantity: lost,
      remarks: remarks || null
    });
    toast(`Equipment returned (${cond}).`, "ok");
    openEquipmentModal();
  } catch (err) {
    toast(err.message || "Failed to return equipment.", "err");
  }
}

function openAddEquipmentModal() {
  const modalHtml = `
    <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
      <div class="modal card inventory-form-modal">
        <div class="modal-head" style="display:flex;justify-content:space-between;align-items:center;">
          <h3>Add Equipment Item</h3>
          <button class="btn ghost sm" type="button" onclick="closeModal()">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
          <div class="field">
            <label for="eqName">Item Name *</label>
            <input id="eqName" class="input" maxlength="150" required placeholder="e.g. Wireless microphone">
          </div>
          <div class="field">
            <label for="eqCode">Inventory Code</label>
            <input id="eqCode" class="input" maxlength="50" placeholder="Generated if blank">
          </div>
          <div class="field">
            <label for="eqSerial">Serial Number / Asset Tag</label>
            <input id="eqSerial" class="input" maxlength="100" placeholder="Optional unique serial number">
          </div>
          <div class="field">
            <label for="eqCategory">Category</label>
            <select id="eqCategory" class="input">
              ${["Sports", "Electronics", "Audio/Visual", "IT", "Accessories", "Other"].map(category => `<option>${category}</option>`).join("")}
            </select>
          </div>
          <div class="field">
            <label for="eqQuantity">Total Quantity *</label>
            <input id="eqQuantity" class="input" type="number" min="1" value="1" required>
          </div>
          <div class="field">
            <label for="eqUnit">Unit</label>
            <input id="eqUnit" class="input" maxlength="50" value="Piece">
          </div>
          <div class="field">
            <label for="eqLocation">Storage Location</label>
            <input id="eqLocation" class="input" maxlength="100" value="Gym">
          </div>
          <div class="field">
            <label for="eqPurchaseDate">Purchase Date</label>
            <input id="eqPurchaseDate" class="input" type="date">
          </div>
          <div class="field inventory-field-full">
            <label for="eqDesc">Description</label>
            <textarea id="eqDesc" class="input" rows="2" placeholder="Specifications, accessories, or notes"></textarea>
          </div>
          </div>

          <div class="modal-foot" style="display:flex;justify-content:flex-end;gap:8px;margin-top:20px;">
            <button class="btn ghost sm" type="button" onclick="closeModal()">Cancel</button>
            <button class="btn primary sm" type="button" onclick="submitEquipment()">Save Item</button>
          </div>
        </div>
      </div>
    </div>
  `;
  $("modalRoot").innerHTML = modalHtml;
}

async function submitEquipment() {
  const name = $("eqName").value.trim();
  const itemCode = $("eqCode").value.trim();
  const serial = $("eqSerial").value.trim();
  const loc = $("eqLocation").value.trim();
  const desc = $("eqDesc").value.trim();
  const quantity = parseInt($("eqQuantity").value, 10);

  if (!name || !quantity || quantity < 1) {
    toast("Enter an equipment name and a valid quantity.", "err");
    return;
  }

  try {
    await api.post("/equipment", {
      item_name: name,
      item_code: itemCode || null,
      serial_no: serial || null,
      category: $("eqCategory").value,
      unit: $("eqUnit").value.trim() || "Piece",
      total_quantity: quantity,
      location: loc || null,
      description: desc || null,
      purchase_date: $("eqPurchaseDate").value || null
    });
    toast("Equipment added to inventory!", "ok");
    closeModal();
    renderResources();
  } catch (err) {
    toast("Error: " + err.message, "err");
  }
}

async function openEditEquipmentModal(itemId) {
  try {
    const item = await api.get(`/equipment/${itemId}`);
    const modalHtml = `
      <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
        <div class="modal card inventory-form-modal">
          <div class="modal-head" style="display:flex;justify-content:space-between;align-items:center;">
            <h3>Edit Equipment</h3>
            <button class="btn ghost sm" type="button" onclick="closeModal()">✕</button>
          </div>
          <div class="modal-body">
            <div class="form-grid">
            <div class="field">
              <label for="eqEditName">Item Name *</label>
              <input id="eqEditName" class="input" maxlength="150" value="${esc(item.item_name)}">
            </div>
            <div class="field">
              <label for="eqEditSerial">Serial / Asset Tag</label>
              <input id="eqEditSerial" class="input" maxlength="100" value="${esc(item.serial_no || "")}">
            </div>
            <div class="field">
              <label for="eqEditCategory">Category</label>
              <select id="eqEditCategory" class="input">
                ${["Sports", "Electronics", "Audio/Visual", "IT", "Accessories", "Other"].map(category => `<option ${item.category === category ? "selected" : ""}>${category}</option>`).join("")}
              </select>
            </div>
            <div class="field">
              <label for="eqEditUnit">Unit</label>
              <input id="eqEditUnit" class="input" maxlength="50" value="${esc(item.unit || "Piece")}">
            </div>
            <div class="field">
              <label for="eqEditLocation">Storage Location</label>
              <input id="eqEditLocation" class="input" maxlength="100" value="${esc(item.location || "")}">
            </div>
            <div class="field">
              <label for="eqEditPurchaseDate">Purchase Date</label>
              <input id="eqEditPurchaseDate" class="input" type="date" value="${esc(item.purchase_date || "")}">
            </div>
            <div class="field">
              <label for="eqEditActive">Inventory Status</label>
              <select id="eqEditActive" class="input"><option value="true" ${item.is_active ? "selected" : ""}>Active</option><option value="false" ${!item.is_active ? "selected" : ""}>Inactive</option></select>
            </div>
            <div class="field inventory-field-full">
              <label for="eqEditDesc">Description</label>
              <textarea id="eqEditDesc" class="input" rows="2">${esc(item.description || "")}</textarea>
            </div>
            </div>
            <div class="modal-foot" style="display:flex;justify-content:flex-end;gap:8px;margin-top:20px;">
              <button class="btn ghost sm" type="button" onclick="closeModal()">Cancel</button>
              <button class="btn primary sm" type="button" onclick="submitEditEquipment(${itemId})">Save</button>
            </div>
          </div>
        </div>
      </div>
    `;
    $("modalRoot").innerHTML = modalHtml;
  } catch (err) {
    toast("Failed: " + err.message, "err");
  }
}

async function submitEditEquipment(itemId) {
  const name = $("eqEditName").value.trim();
  if (!name) {
    toast("Equipment name is required.", "err");
    return;
  }

  try {
    await api.put(`/equipment/${itemId}`, {
      item_name: name,
      serial_no: $("eqEditSerial").value.trim() || null,
      category: $("eqEditCategory").value,
      unit: $("eqEditUnit").value.trim() || "Piece",
      location: $("eqEditLocation").value.trim(),
      purchase_date: $("eqEditPurchaseDate").value || null,
      description: $("eqEditDesc").value.trim(),
      is_active: $("eqEditActive").value === "true"
    });
    toast("Equipment updated successfully!", "ok");
    closeModal();
    renderResources();
  } catch (err) {
    toast("Error: " + err.message, "err");
  }
}

async function openEquipmentDetails(itemId) {
  try {
    const item = await api.get(`/equipment/${itemId}`);
    const movements = (isAdmin() || isStaff())
      ? await api.get(`/equipment/${itemId}/movements`)
      : [];
    $("modalRoot").innerHTML = `
      <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
        <div class="modal card inventory-detail-modal">
          <div class="modal-head"><div><h2>${esc(item.item_name)}</h2><p class="muted">${esc(item.item_code)} · ${esc(item.category)}</p></div><button class="btn icon" type="button" onclick="closeModal()">✕</button></div>
          <div class="modal-body">
            <div class="inventory-detail-grid">
              <div><span>Serial / Asset Tag</span><strong>${esc(item.serial_no || "Not recorded")}</strong></div>
              <div><span>Storage location</span><strong>${esc(item.location || "—")}</strong></div>
              <div><span>Availability</span><strong>${item.available_quantity ?? 0} / ${item.total_quantity} ${esc(item.unit || "Piece")} available</strong></div>
              <div><span>Condition</span><strong>${esc(item.condition_status || "Good")}</strong></div>
              <div><span>Reserved</span><strong>${item.reserved_quantity ?? 0}</strong></div>
              <div><span>Maintenance / damaged / lost</span><strong>${item.maintenance_quantity ?? 0} / ${item.damaged_quantity ?? 0} / ${item.lost_quantity ?? 0}</strong></div>
            </div>
            <p>${esc(item.description || "No description provided.")}</p>
            ${movements.length ? `<h3>Recent stock activity</h3><div class="schedule">${movements.slice(0, 5).map(movement => `<div class="slot"><time>${fmtShort(movement.created_at)}</time><div><div class="t">${esc(movement.movement_type)} · ${movement.quantity}</div><div class="s">${esc(movement.notes || "")}</div></div></div>`).join("")}</div>` : ""}
            <div class="modal-foot"><button class="btn ghost" type="button" onclick="closeModal()">Close</button></div>
          </div>
        </div>
      </div>`;
  } catch (err) {
    toast(`Failed to load equipment details: ${err.message}`, "err");
  }
}

// Global window registrations
window.openEquipmentModal = openEquipmentModal;
window.openEquipmentDetails = openEquipmentDetails;
window.submitEquipment = submitEquipment;
window.openEditEquipmentModal = openEditEquipmentModal;
window.submitEditEquipment = submitEditEquipment;

/* =========================================================
   User-Facing Equipment Booking Module (Quantity-based)
   ========================================================= */

let selectedEquipmentQuantities = {};

async function renderBookEquipment() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading sports and electronic equipment inventory...</div>`;

  try {
    const items = await api.get("/equipment");
    selectedEquipmentQuantities = {};

    const now = new Date();
    now.setHours(now.getHours() + 1, 0, 0, 0);
    const later = new Date(now.getTime() + 2 * 3600 * 1000);

    const categories = ["All", "Sports", "Audio/Visual", "Electronics", "IT", "Accessories", "Other"];

    host.innerHTML = `
      <div style="max-width:1050px; margin:0 auto;">
        <div class="panel pad" style="margin-bottom:20px; background:linear-gradient(135deg, rgba(99,102,241,0.06), rgba(168,85,247,0.04));">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:12px;">
            <div>
              <h3 style="margin:0 0 4px 0;">Reserve Equipment</h3>
              <p class="muted" style="margin:0; font-size:14px;">Select sports gear or electronic devices and specify the required quantity.</p>
            </div>
            <div style="padding:6px 14px; background:rgba(99,102,241,0.12); border-radius:20px; font-size:13px; font-weight:600; color:var(--primary);">
              📍 Handover Location: Gym Equipment Desk
            </div>
          </div>
        </div>

        <div class="split" style="align-items:flex-start; gap:24px;">
          <!-- Left: Equipment Selection List -->
          <div style="flex:1.6;">
            <div style="display:flex; gap:8px; margin-bottom:16px; overflow-x:auto; padding-bottom:4px;">
              ${categories.map(c => `
                <button type="button" class="btn ghost sm cat-filter-btn ${c==='All'?'primary':''}" onclick="filterEquipmentCards('${c}', this)">${c}</button>
              `).join('')}
            </div>

            <div id="equipmentCardsGrid" style="display:grid; grid-template-columns:repeat(auto-fill, minmax(280px, 1fr)); gap:16px;">
              ${renderEquipmentCardItems(items, "All")}
            </div>
          </div>

          <!-- Right: Reservation Form & Cart -->
          <div class="panel pad" style="flex:1; position:sticky; top:20px;">
            <h4 style="margin-top:0; margin-bottom:16px;">Booking Details</h4>

            <div class="field" style="margin-bottom:12px;">
              <label for="eqBookStart" style="font-size:13px; font-weight:600; display:block; margin-bottom:4px;">Start Date &amp; Time</label>
              <input id="eqBookStart" type="datetime-local" class="input" value="${toLocalInput(now)}" style="width:100%;">
            </div>

            <div class="field" style="margin-bottom:12px;">
              <label for="eqBookEnd" style="font-size:13px; font-weight:600; display:block; margin-bottom:4px;">End Date &amp; Time</label>
              <input id="eqBookEnd" type="datetime-local" class="input" value="${toLocalInput(later)}" style="width:100%;">
            </div>

            <div class="field" style="margin-bottom:16px;">
              <label for="eqBookPurpose" style="font-size:13px; font-weight:600; display:block; margin-bottom:4px;">Purpose / Event</label>
              <input id="eqBookPurpose" type="text" class="input" placeholder="e.g. Inter-college Basketball Practice" style="width:100%;">
            </div>

            <div style="border-top:1px solid rgba(0,0,0,0.08); padding-top:14px; margin-bottom:16px;">
              <div style="font-size:13px; font-weight:600; margin-bottom:8px;">Selected Items:</div>
              <div id="selectedEquipmentSummary" style="font-size:13px; color:var(--muted); min-height:48px;">
                No equipment selected yet. Use the + / - buttons to select quantities.
              </div>
            </div>

            <button type="button" class="btn primary" style="width:100%; justify-content:center;" onclick="submitEquipmentReservation()">
              Confirm Equipment Request
            </button>
          </div>
        </div>
      </div>
    `;

    window.rawEquipmentList = items;
  } catch (err) {
    host.innerHTML = `<div class="empty">Failed to load equipment catalog: ${esc(err.message)}</div>`;
  }
}

function renderEquipmentCardItems(items, filterCat) {
  if (!items || !items.length) {
    return `<div class="hint neutral" style="grid-column:1/-1;">No equipment available in inventory.</div>`;
  }

  const filtered = items.filter(it => {
    if (filterCat === "All") return true;
    const cat = it.category || it.category_name || it.item_category || "Other";
    return cat.toLowerCase().includes(filterCat.toLowerCase());
  });

  if (!filtered.length) {
    return `<div class="hint neutral" style="grid-column:1/-1;">No equipment found in ${esc(filterCat)} category.</div>`;
  }

  return filtered.map(it => {
    const avail = (it.available_quantity !== undefined && it.available_quantity !== null)
      ? it.available_quantity
      : (it.availability_status === 'Available' ? 1 : 0);
    const cat = it.category || it.category_name || it.item_category || "Other";
    const curQty = selectedEquipmentQuantities[it.item_id] || 0;

    return `
      <div class="panel pad card" style="display:flex; flex-direction:column; justify-content:space-between; border:1px solid rgba(0,0,0,0.06);">
        <div>
          <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:6px;">
            <span class="pill info" style="font-size:11px;">${esc(cat)}</span>
            <span class="pill ${avail > 0 ? 'ok' : 'err'}" style="font-size:11px;">
              ${avail > 0 ? `${avail} in Stock` : 'Out of Stock'}
            </span>
          </div>
          <h4 style="margin:4px 0 6px 0; font-size:15px;">${esc(it.item_name)}</h4>
          <p class="muted" style="font-size:12px; margin:0 0 10px 0;">Location: <b>${esc(it.location || 'Gym')}</b></p>
        </div>

        <div style="display:flex; justify-content:space-between; align-items:center; margin-top:12px; border-top:1px dashed rgba(0,0,0,0.08); padding-top:10px;">
          <span style="font-size:12px; font-weight:600;">Quantity:</span>
          <div style="display:flex; align-items:center; gap:8px;">
            <button type="button" class="btn ghost sm" style="padding:2px 8px;" onclick="changeEquipQty(${it.item_id}, -1, ${avail})">-</button>
            <span id="qty_val_${it.item_id}" style="font-weight:700; min-width:20px; text-align:center;">${curQty}</span>
            <button type="button" class="btn ghost sm" style="padding:2px 8px;" onclick="changeEquipQty(${it.item_id}, 1, ${avail})" ${avail <= 0 ? 'disabled' : ''}>+</button>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function filterEquipmentCards(category, btnEl) {
  document.querySelectorAll(".cat-filter-btn").forEach(b => {
    b.classList.remove("primary");
    b.classList.add("ghost");
  });
  if (btnEl) {
    btnEl.classList.remove("ghost");
    btnEl.classList.add("primary");
  }
  const grid = $("equipmentCardsGrid");
  if (grid && window.rawEquipmentList) {
    grid.innerHTML = renderEquipmentCardItems(window.rawEquipmentList, category);
  }
}

function changeEquipQty(itemId, delta, maxAvail) {
  const current = selectedEquipmentQuantities[itemId] || 0;
  let next = current + delta;
  if (next < 0) next = 0;
  if (next > maxAvail) {
    toast(`Maximum available quantity for this item is ${maxAvail}`, "err");
    next = maxAvail;
  }

  if (next === 0) {
    delete selectedEquipmentQuantities[itemId];
  } else {
    selectedEquipmentQuantities[itemId] = next;
  }

  const valEl = $(`qty_val_${itemId}`);
  if (valEl) valEl.textContent = next;

  updateEquipmentSummary();
}

function updateEquipmentSummary() {
  const sumEl = $("selectedEquipmentSummary");
  if (!sumEl) return;

  const entries = Object.entries(selectedEquipmentQuantities);
  if (!entries.length) {
    sumEl.innerHTML = `<span class="muted">No equipment selected yet. Use the + / - buttons to select quantities.</span>`;
    return;
  }

  const itemsMap = {};
  (window.rawEquipmentList || []).forEach(it => { itemsMap[it.item_id] = it; });

  const rows = entries.map(([id, qty]) => {
    const it = itemsMap[id] || { item_name: `Item #${id}` };
    return `<div style="display:flex; justify-content:space-between; margin-bottom:4px;">
      <span>${esc(it.item_name)}</span>
      <b>× ${qty}</b>
    </div>`;
  }).join('');

  sumEl.innerHTML = rows;
}

async function submitEquipmentReservation() {
  const entries = Object.entries(selectedEquipmentQuantities);
  if (!entries.length) {
    toast("Please select at least one equipment item and quantity.", "err");
    return;
  }

  const start = $("eqBookStart").value;
  const end = $("eqBookEnd").value;
  const purpose = ($("eqBookPurpose").value || "").trim();

  if (!start || !end) {
    toast("Please specify start and end dates/times.", "err");
    return;
  }

  if (new Date(start) >= new Date(end)) {
    toast("End time must be after start time.", "err");
    return;
  }

  if (!purpose) {
    toast("Please enter the purpose for this reservation.", "err");
    return;
  }

  const equipment_requests = entries.map(([id, qty]) => ({
    item_id: parseInt(id, 10),
    quantity: qty
  }));

  try {
    const payload = {
      purpose: purpose,
      equipment_requests: equipment_requests,
      start_time: start,
      end_time: end
    };

    const booking = await api.post("/bookings", payload);
    if (!booking || !booking.booking_id) {
      throw new Error("The server did not confirm the reservation.");
    }
    toast(`Equipment request BK-${booking.booking_id} submitted! Awaiting Admin approval.`, "ok");
    selectedEquipmentQuantities = {};
    if (typeof checkBadges === "function") checkBadges();
    if (typeof go === "function") {
      go("mybookings");
    }
  } catch (err) {
    toast("Reservation failed: " + err.message, "err");
  }
}

window.renderBookEquipment = renderBookEquipment;
window.filterEquipmentCards = filterEquipmentCards;
window.changeEquipQty = changeEquipQty;
window.submitEquipmentReservation = submitEquipmentReservation;
