/* =========================================================
   Smart Campus — Equipment Inventory & Handover Module
   ========================================================= */

async function openEquipmentModal() {
  try {
    const items = await api.get("/equipment");

    let rowsHtml = "";
    if (items.length) {
      rowsHtml = items.map(eq => {
        const canManage = isAdmin() || isStaff();
        return `
          <tr>
            <td class="cell-strong"><b>${esc(eq.item_name)}</b></td>
            <td><span class="code">${esc(eq.serial_no || '—')}</span></td>
            <td>${esc(eq.location || 'Media Store')}</td>
            <td>
              <span class="pill ${eq.availability_status==='Available'?'ok':eq.availability_status==='Issued'?'warn':'err'}">
                ${esc(eq.availability_status)}
              </span>
            </td>
            <td><span class="pill ${eq.condition_status==='Good'?'ok':'bad'}">${esc(eq.condition_status)}</span></td>
            ${canManage ? `
              <td style="white-space:nowrap;">
                ${eq.availability_status === 'Available' ? `
                  <button class="btn ok sm" type="button" onclick="openIssueEquipmentModal(${eq.item_id}, '${esc(eq.item_name)}')">Issue</button>
                ` : ''}
                ${eq.availability_status === 'Issued' ? `
                  <button class="btn warn sm" type="button" onclick="openReturnEquipmentModal(${eq.item_id}, '${esc(eq.item_name)}')">Return</button>
                ` : ''}
                ${isAdmin() ? `
                  <button class="btn ghost sm" type="button" onclick="openEditEquipmentModal(${eq.item_id})">Edit</button>
                ` : ''}
              </td>
            ` : ''}
          </tr>
        `;
      }).join("");
    } else {
      rowsHtml = `<tr><td colspan="6" class="empty">No equipment items found.</td></tr>`;
    }

    const modalHtml = `
      <div class="modal-backdrop" onclick="if(event.target===this)closeModal()">
        <div class="modal wide card" style="max-width:850px;margin:auto;">
          <div class="modal-head" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
            <div>
              <h3>Media & Equipment Inventory</h3>
              <p class="sub" style="margin:0;">Track physical checkout, handover and returns of projectors, audio & lab gear.</p>
            </div>
            <button class="btn ghost sm" type="button" onclick="closeModal()">✕</button>
          </div>
          <div class="modal-body">
            ${isAdmin() ? `
              <div style="display:flex;justify-content:flex-end;margin-bottom:14px">
                <button class="btn primary sm" type="button" onclick="openAddEquipmentModal()">+ Add Equipment Item</button>
              </div>
            ` : ''}
            <div class="table-wrap">
              <table class="table">
                <thead>
                  <tr>
                    <th>Item Name</th>
                    <th>Serial / Tag</th>
                    <th>Location</th>
                    <th>Availability</th>
                    <th>Condition</th>
                    ${isAdmin() || isStaff() ? `<th>Handover & Actions</th>` : ''}
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
    toast("Failed to load equipment: " + err.message, "err");
  }
}

function openIssueEquipmentModal(itemId, itemName) {
  const root = $("modalRoot");
  root.innerHTML = `
    <div class="modal-backdrop" onclick="if(event.target===this)openEquipmentModal()">
      <div class="modal card" style="max-width:440px;margin:auto;">
        <h3>Issue Equipment: ${esc(itemName)}</h3>
        <p class="sub">Record physical handover of item to the booking requester.</p>

        <div class="field">
          <label>Approved Booking ID *</label>
          <input id="issueBookingId" class="input" type="number" placeholder="e.g. 101">
          <span class="muted" style="font-size:12px;">Booking must be in 'Approved' state.</span>
        </div>

        <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:20px;">
          <button class="btn ghost sm" type="button" onclick="openEquipmentModal()">Cancel</button>
          <button class="btn primary sm" type="button" onclick="submitIssueEquipment(${itemId})">Confirm Issue</button>
        </div>
      </div>
    </div>
  `;
}

async function submitIssueEquipment(itemId) {
  const bId = parseInt($("issueBookingId").value, 10);
  if (!bId) {
    toast("Please enter an Approved Booking ID.", "err");
    return;
  }

  try {
    await api.post(`/equipment/${itemId}/issue`, { booking_id: bId });
    toast("Equipment issued successfully!", "ok");
    openEquipmentModal();
  } catch (err) {
    toast(err.message || "Failed to issue equipment.", "err");
  }
}

function openReturnEquipmentModal(itemId, itemName) {
  const root = $("modalRoot");
  root.innerHTML = `
    <div class="modal-backdrop" onclick="if(event.target===this)openEquipmentModal()">
      <div class="modal card" style="max-width:460px;margin:auto;">
        <h3>Return Equipment: ${esc(itemName)}</h3>
        <p class="sub">Inspect condition and restore equipment to active inventory.</p>

        <div class="field">
          <label>Condition on Return *</label>
          <select id="returnCond" class="input">
            <option value="Good">Good (Restores Availability)</option>
            <option value="Damaged">Damaged (Sends to Maintenance)</option>
          </select>
        </div>

        <div class="field">
          <label>Inspection Notes / Remarks</label>
          <textarea id="returnRemarks" class="input" rows="3" placeholder="Condition details, missing accessories, cables returned..."></textarea>
        </div>

        <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:20px;">
          <button class="btn ghost sm" type="button" onclick="openEquipmentModal()">Cancel</button>
          <button class="btn primary sm" type="button" onclick="submitReturnEquipment(${itemId})">Record Return</button>
        </div>
      </div>
    </div>
  `;
}

async function submitReturnEquipment(itemId) {
  const cond = $("returnCond").value;
  const remarks = $("returnRemarks").value.trim();

  try {
    await api.post(`/equipment/${itemId}/return`, {
      condition_on_return: cond,
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
    <div class="modal-backdrop" onclick="if(event.target===this)openEquipmentModal()">
      <div class="modal card" style="max-width:460px;margin:auto;">
        <div class="modal-head" style="display:flex;justify-content:space-between;align-items:center;">
          <h3>Add Equipment Item</h3>
          <button class="btn ghost sm" type="button" onclick="openEquipmentModal()">✕</button>
        </div>
        <div class="modal-body" style="margin-top:14px;">
          <div class="field">
            <label for="eqName">Item Name *</label>
            <input id="eqName" class="input" placeholder="e.g. Wireless Mic Receiver, Projector">
          </div>

          <div class="field">
            <label for="eqSerial">Serial Number / Asset Tag</label>
            <input id="eqSerial" class="input" placeholder="e.g. EQ-MIC-01">
          </div>

          <div class="field">
            <label for="eqLocation">Storage Location</label>
            <input id="eqLocation" class="input" value="Media Store" placeholder="Store room, Block D...">
          </div>

          <div class="field">
            <label for="eqCond">Condition</label>
            <select id="eqCond" class="input">
              <option value="Good">Good</option>
              <option value="Damaged">Damaged</option>
            </select>
          </div>

          <div class="field">
            <label for="eqDesc">Description</label>
            <textarea id="eqDesc" class="input" rows="2" placeholder="Specifications, cables, accessories..."></textarea>
          </div>

          <div class="modal-foot" style="display:flex;justify-content:flex-end;gap:8px;margin-top:20px;">
            <button class="btn ghost sm" type="button" onclick="openEquipmentModal()">Back</button>
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
  const serial = $("eqSerial").value.trim();
  const loc = $("eqLocation").value.trim();
  const cond = $("eqCond").value;
  const desc = $("eqDesc").value.trim();

  if (!name) {
    toast("Item name is required.", "err");
    return;
  }

  try {
    await api.post("/equipment", {
      item_name: name,
      serial_no: serial || null,
      location: loc || null,
      condition_status: cond,
      availability_status: "Available",
      description: desc || null
    });
    toast("Equipment added to inventory!", "ok");
    openEquipmentModal();
  } catch (err) {
    toast("Error: " + err.message, "err");
  }
}

async function openEditEquipmentModal(itemId) {
  try {
    const item = await api.get(`/equipment/${itemId}`);
    const modalHtml = `
      <div class="modal-backdrop" onclick="if(event.target===this)openEquipmentModal()">
        <div class="modal card" style="max-width:460px;margin:auto;">
          <div class="modal-head" style="display:flex;justify-content:space-between;align-items:center;">
            <h3>Edit Equipment</h3>
            <button class="btn ghost sm" type="button" onclick="openEquipmentModal()">✕</button>
          </div>
          <div class="modal-body" style="margin-top:14px;">
            <div class="field">
              <label for="eqEditName">Item Name</label>
              <input id="eqEditName" class="input" value="${esc(item.item_name)}">
            </div>

            <div class="field">
              <label for="eqEditStatus">Availability Status</label>
              <select id="eqEditStatus" class="input">
                <option value="Available" ${item.availability_status==='Available'?'selected':''}>Available</option>
                <option value="Issued" ${item.availability_status==='Issued'?'selected':''}>Issued</option>
                <option value="Maintenance" ${item.availability_status==='Maintenance'?'selected':''}>Maintenance</option>
              </select>
            </div>

            <div class="field">
              <label for="eqEditCond">Condition</label>
              <select id="eqEditCond" class="input">
                <option value="Good" ${item.condition_status==='Good'?'selected':''}>Good</option>
                <option value="Damaged" ${item.condition_status==='Damaged'?'selected':''}>Damaged</option>
              </select>
            </div>

            <div class="modal-foot" style="display:flex;justify-content:flex-end;gap:8px;margin-top:20px;">
              <button class="btn ghost sm" type="button" onclick="openEquipmentModal()">Back</button>
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
  const status = $("eqEditStatus").value;
  const cond = $("eqEditCond").value;

  try {
    await api.put(`/equipment/${itemId}`, {
      item_name: name,
      availability_status: status,
      condition_status: cond
    });
    toast("Equipment updated successfully!", "ok");
    openEquipmentModal();
  } catch (err) {
    toast("Error: " + err.message, "err");
  }
}

// Global window registrations
window.openEquipmentModal = openEquipmentModal;
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
