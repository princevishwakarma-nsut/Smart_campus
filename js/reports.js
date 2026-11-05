let dashboardRange = "30";

function setDashboardRange(range) {
  dashboardRange = range;
  renderAdminDash();
}

async function renderAdminDash() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading campus overview...</div>`;

  $("topActions").innerHTML = `
    <select class="input sm" aria-label="Dashboard date range" onchange="setDashboardRange(this.value)">
      <option value="7" ${dashboardRange === "7" ? "selected" : ""}>Last 7 days</option>
      <option value="30" ${dashboardRange === "30" ? "selected" : ""}>Last 30 days</option>
      <option value="90" ${dashboardRange === "90" ? "selected" : ""}>Last 90 days</option>
      <option value="all" ${dashboardRange === "all" ? "selected" : ""}>All time</option>
    </select>
  `;

  try {
    const params = {};
    if (dashboardRange !== "all") {
      const end = new Date();
      const start = new Date(end);
      start.setDate(start.getDate() - Number(dashboardRange) + 1);
      params.start_date = toLocalInput(start).split("T")[0];
      params.end_date = toLocalInput(end).split("T")[0];
    }
    const stats = await api.get("/reports/dashboard", params);
    updatePendingBadge(stats.pending_approvals);
    const bookingsToday = stats.bookings_today ?? 0;
    const equipmentTypes = stats.equipment_types ?? 0;
    const equipmentUnits = stats.equipment_units ?? 0;
    const maintenanceTickets = stats.maintenance_tickets ?? 0;

    let upcomingHtml = "";
    if (stats.upcoming_bookings && stats.upcoming_bookings.length) {
      upcomingHtml = stats.upcoming_bookings.map(ub => `
        <div class="slot">
          <time>${fmtShort(ub.start_time)}</time>
          <div>
            <div class="t">${esc(ub.resource_name)} - ${esc(ub.purpose)}</div>
            <div class="s">Requester: ${esc(ub.user_name)} | <span class="pill ${ub.status==='Approved'?'ok':'warn'}">${esc(ub.status)}</span></div>
          </div>
        </div>
      `).join("");
    } else {
      upcomingHtml = `<div class="hint neutral">No upcoming bookings scheduled for today.</div>`;
    }

    let catBarsHtml = "";
    if (stats.category_distribution && stats.category_distribution.length) {
      const maxCount = Math.max(...stats.category_distribution.map(c => c.resource_count), 1);
      catBarsHtml = stats.category_distribution.map(c => {
        const pct = Math.round((c.resource_count / maxCount) * 100);
        return `
          <div class="barrow">
            <span>${esc(c.category_name)}</span>
            <div class="bar"><i style="width:${pct}%"></i></div>
            <span class="v">${c.resource_count}</span>
          </div>
        `;
      }).join("");
    }

    const adminName = (getCurrentUser()?.name || "Administrator").trim().split(/\s+/)[0];
    const todayLabel = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric" }).format(new Date());
    const html = `
      <section class="admin-welcome"><div><span class="admin-eyebrow">CAMPUS OVERVIEW <span aria-hidden="true">|</span> ${esc(todayLabel)}</span>
        <h2>Welcome back, ${esc(adminName)}</h2><p>Here is what is happening across your campus today.</p></div><div class="admin-welcome-mark" aria-hidden="true">SC</div></section>
      <section class="admin-kpis" aria-label="Campus performance">
        <article class="admin-kpi"><span class="admin-kpi-icon">R</span><div><span>Campus spaces</span><strong>${stats.total_resources}</strong><small>${stats.available_resources} available now</small></div></article>
        <button type="button" class="admin-kpi admin-kpi-action" onclick="go('approvals')"><span class="admin-kpi-icon admin-kpi-icon-warn">!</span><div><span>Pending approvals</span><strong>${stats.pending_approvals}</strong><small>Review booking requests <b aria-hidden="true">&gt;</b></small></div></button>
        <article class="admin-kpi"><span class="admin-kpi-icon admin-kpi-icon-green">OK</span><div><span>Approved bookings</span><strong>${stats.approved_bookings}</strong><small>In the selected period</small></div></article>
        <article class="admin-kpi"><span class="admin-kpi-icon admin-kpi-icon-purple">B</span><div><span>Bookings today</span><strong>${bookingsToday}</strong><small>${stats.total_bookings} in the selected period</small></div></article>
      </section>
      <section class="admin-insights" aria-label="Inventory and maintenance">
        <article class="admin-insight"><span class="admin-insight-icon">+</span><div><span>Equipment inventory</span><strong>${equipmentTypes} <small>types</small></strong><p>${equipmentUnits} units in inventory</p></div></article>
        <article class="admin-insight"><span class="admin-insight-icon admin-insight-icon-alert">!</span><div><span>Open maintenance</span><strong>${maintenanceTickets}</strong><p>Tickets awaiting resolution</p></div></article>
        <article class="admin-insight"><span class="admin-insight-icon admin-insight-icon-blue">^</span><div><span>Total bookings</span><strong>${stats.total_bookings}</strong><p>Across the selected period</p></div></article>
      </section>
      <section class="admin-overview-grid">
        <article class="panel pad admin-content-panel"><div class="admin-panel-heading"><div><span class="admin-eyebrow">TODAY</span><h3>Upcoming campus sessions</h3></div><button type="button" class="btn ghost sm" onclick="go('allbookings')">All bookings <span aria-hidden="true">&gt;</span></button></div>
          <div class="schedule">${upcomingHtml}</div></article>
        <article class="panel pad admin-content-panel"><div class="admin-panel-heading"><div><span class="admin-eyebrow">CAMPUS SPACES</span><h3>Resources by category</h3></div></div>
          <div class="bars">${catBarsHtml || `<div class="hint neutral">No resource categories to display.</div>`}</div></article>
      </section>
      <section class="panel pad admin-content-panel admin-activity-panel"><div class="admin-panel-heading"><div><span class="admin-eyebrow">LATEST UPDATES</span><h3>Recent booking activity</h3></div><button type="button" class="btn ghost sm" onclick="go('audit')">View audit trail <span aria-hidden="true">&gt;</span></button></div>
        <div class="schedule">${stats.recent_activity && stats.recent_activity.length ? stats.recent_activity.map(activity => `
          <div class="slot"><time>${fmtShort(activity.changed_at)}</time><div><div class="t">BK-${activity.booking_id} | ${esc(activity.action)}</div>
            <div class="s">${esc(activity.purpose || "Booking")} | ${esc(activity.actor_name || "System")}${activity.remarks ? ` | ${esc(activity.remarks)}` : ""}</div></div></div>`).join("") : `<div class="hint neutral">No recent booking activity in this date range.</div>`}</div>
      </section>
    `;

    host.innerHTML = html;
  } catch (err) {
    host.innerHTML = `<div class="empty">Failed to load overview: ${esc(err.message)}</div>`;
  }
}

async function renderReports() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Generating utilization reports...</div>`;

  try {
    const data = await api.get("/reports/resource-utilization");

    let busiestHtml = "";
    if (data.busiest_resources && data.busiest_resources.length) {
      busiestHtml = data.busiest_resources.map(r => `
        <tr>
          <td class="cell-strong">${esc(r.resource_name)}</td>
          <td><span class="tag">${esc(r.category_name)}</span></td>
          <td><b>${r.booking_count}</b> bookings</td>
          <td>${Math.round(r.hours_booked)} hrs</td>
        </tr>
      `).join("");
    } else {
      busiestHtml = `<tr><td colspan="4" class="empty">No booking activity recorded yet.</td></tr>`;
    }

    let peakBarsHtml = "";
    if (data.peak_hours && data.peak_hours.length) {
      const maxCount = Math.max(...data.peak_hours.map(p => p.count), 1);
      peakBarsHtml = `
        <div class="hourbars">
          ${data.peak_hours.map(p => {
            const h = p.hour;
            const height = Math.max(8, Math.round((p.count / maxCount) * 110));
            return `
              <div style="height:${height}px" title="${h}:00 - ${p.count} bookings">
                <span>${h}h</span>
              </div>
            `;
          }).join("")}
        </div>
      `;
    } else {
      peakBarsHtml = `<div class="hint neutral" style="margin-top:20px">No hourly data available yet.</div>`;
    }

    const html = `
      <div class="kpis">
        <div class="kpi">
          <div class="n">${data.total_hours_booked}</div>
          <div class="l">Total Hours Utilized</div>
        </div>
        <div class="kpi">
          <div class="n" style="color:var(--ok)">${data.status_breakdown["Approved"] || 0}</div>
          <div class="l">Approved Bookings</div>
        </div>
        <div class="kpi">
          <div class="n" style="color:var(--warn)">${data.status_breakdown["Pending"] || 0}</div>
          <div class="l">Pending Requests</div>
        </div>
        <div class="kpi">
          <div class="n" style="color:var(--bad)">${data.status_breakdown["Cancelled"] || 0}</div>
          <div class="l">Cancellations</div>
        </div>
      </div>

      <div class="split">
        <div class="panel">
          <div class="panel-head">
            <h3>Most Utilized Spaces</h3>
          </div>
          <table>
            <thead>
              <tr>
                <th>Space</th>
                <th>Category</th>
                <th>Requests</th>
                <th>Hours Booked</th>
              </tr>
            </thead>
            <tbody>${busiestHtml}</tbody>
          </table>
        </div>

        <div class="panel pad">
          <h3>Peak Booking Hours</h3>
          <p class="muted" style="margin-bottom:18px">Distribution of reservations throughout the day (8:00 to 20:00).</p>
          ${peakBarsHtml}
        </div>
      </div>
    `;

    host.innerHTML = html;
  } catch (err) {
    host.innerHTML = `<div class="empty">Failed to load reports: ${esc(err.message)}</div>`;
  }
}

let auditCurrentPage = 1;
const AUDIT_PAGE_LIMIT = 25;
let auditSearchQuery = "";

async function renderAudit(page = 1) {
  auditCurrentPage = Math.max(1, page);
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading system audit trail...</div>`;

  try {
    const params = {
      limit: AUDIT_PAGE_LIMIT + 1,
      offset: (auditCurrentPage - 1) * AUDIT_PAGE_LIMIT
    };
    if (auditSearchQuery) params.q = auditSearchQuery;

    const list = await api.get("/reports/audit", params);
    const hasMore = Array.isArray(list) && list.length > AUDIT_PAGE_LIMIT;
    const pageItems = hasMore ? list.slice(0, AUDIT_PAGE_LIMIT) : (Array.isArray(list) ? list : []);

    let html = `
      <div class="panel">
        <div class="panel-head">
          <h3>Audit Log Trail (Page ${auditCurrentPage})</h3>
          <div class="actions">
            <input id="audSearch" class="input sm" placeholder="Search trail..." value="${esc(auditSearchQuery)}" onchange="onAuditSearchChange(this.value)">
          </div>
        </div>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Action</th>
              <th>Actor</th>
              <th>Target Booking</th>
              <th>Timestamp</th>
              <th>Remarks</th>
            </tr>
          </thead>
          <tbody id="audTableBody">
    `;

    if (!pageItems.length) {
      html += `<tr><td colspan="6" class="empty">No audit history recorded matching this filter.</td></tr>`;
    } else {
      for (const a of pageItems) {
        const actionPill = a.action === "Approved" ? "ok" : (a.action === "Rejected" || a.action === "Cancelled" ? "bad" : "info");
        html += `
          <tr>
            <td><span class="code">${esc(a.id)}</span></td>
            <td><span class="pill ${actionPill}">${esc(a.action)}</span></td>
            <td><b>${esc(a.changed_by)}</b> <span class="muted">(${esc(a.changed_by_role)})</span></td>
            <td>${a.booking_id ? `<button class="link-btn" onclick="openBookingHistory(${a.raw_booking_id})">${esc(a.booking_id)}</button>` : '—'}</td>
            <td>${fmt(a.changed_at)}</td>
            <td style="max-width:280px">${esc(a.remarks || '—')}</td>
          </tr>
        `;
      }
    }

    html += `</tbody></table>
      <div style="display:flex; justify-content:space-between; align-items:center; padding:12px 16px; border-top:1px solid var(--border,#e2e8f0); background:var(--bg-subtle,transparent);">
        <span class="muted" style="font-size:13px;">Showing page ${auditCurrentPage} (${pageItems.length} records)</span>
        <div style="display:flex; gap:8px;">
          <button class="btn ghost sm" type="button" ${auditCurrentPage <= 1 ? 'disabled' : ''} onclick="renderAudit(${auditCurrentPage - 1})">← Previous</button>
          <button class="btn ghost sm" type="button" ${!hasMore ? 'disabled' : ''} onclick="renderAudit(${auditCurrentPage + 1})">Next →</button>
        </div>
      </div>
    </div>`;
    host.innerHTML = html;
  } catch (err) {
    host.innerHTML = `<div class="empty">Failed to load audit trail: ${esc(err.message)}</div>`;
  }
}

function onAuditSearchChange(val) {
  auditSearchQuery = (val || "").trim();
  renderAudit(1);
}

function filterAuditTable(val) {
  auditSearchQuery = (val || "").trim();
  renderAudit(1);
}

async function renderFacultyDash() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading your schedule...</div>`;

  try {
    const bookings = await api.get("/bookings/my");
    const now = new Date();
    const upcoming = bookings
      .filter(b => {
        const endTime = b.end_time || (b.resources && b.resources[0] && b.resources[0].end_time);
        return b.status === "Approved" && endTime && parseCampusDatetime(endTime) >= now;
      })
      .sort((a, b) => parseCampusDatetime(a.start_time) - parseCampusDatetime(b.start_time))
      .slice(0, 5);

    let bkHtml = "";
    if (upcoming.length) {
      bkHtml = upcoming.map(b => {
        const r = (b.resources && b.resources[0]) || {};
        return `
          <div class="slot">
            <time>${fmtShort(b.start_time || r.start_time)}</time>
            <div>
              <div class="t">${esc(b.purpose)}</div>
              <div class="s">${esc(r.resource_name || 'Equipment only')} Â· <span class="pill ok">Approved</span></div>
            </div>
          </div>
        `;
      }).join("");
    } else {
      bkHtml = `<div class="hint neutral">No upcoming approved bookings.</div>`;
    }

    const firstName = (getCurrentUser()?.name || "there").trim().split(/\s+/)[0];
    const dateLabel = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric" }).format(now);
    const html = `
      <section class="faculty-welcome">
        <div class="faculty-welcome-copy"><span class="faculty-eyebrow">FACULTY WORKSPACE <span aria-hidden="true">Â·</span> ${esc(dateLabel)}</span>
          <h2>Good day, ${esc(firstName)}</h2><p>Your campus bookings and schedule, all in one place.</p></div>
        <div class="faculty-welcome-mark" aria-hidden="true">SC</div>
      </section>
      <section class="faculty-stats" aria-label="Booking summary">
        <article class="faculty-stat"><span class="faculty-stat-icon" aria-hidden="true">â–¦</span><div><span>Upcoming bookings</span><strong>${upcoming.length}</strong></div></article>
        <article class="faculty-stat"><span class="faculty-stat-icon faculty-stat-icon-soft" aria-hidden="true">âœ“</span><div><span>Approved and ready</span><strong>${upcoming.length ? "All set" : "No bookings"}</strong></div></article>
        <article class="faculty-stat"><span class="faculty-stat-icon faculty-stat-icon-muted" aria-hidden="true">â—·</span><div><span>Next booking</span><strong>${upcoming.length ? esc(fmtShort(upcoming[0].start_time || upcoming[0].resources?.[0]?.start_time)) : "Whenever you need it"}</strong></div></article>
      </section>
      <section class="panel pad faculty-bookings-panel">
        <div class="faculty-panel-heading"><div><span class="faculty-eyebrow">YOUR SCHEDULE</span><h3>Upcoming approved bookings</h3></div>
          <button type="button" class="btn ghost sm" onclick="go('myschedule')">View schedule <span aria-hidden="true">â†’</span></button></div>
        <div class="schedule">${bkHtml}</div>
      </section>
      <section class="faculty-shortcuts" aria-label="Quick actions">
        <button type="button" class="faculty-shortcut" onclick="go('catalog')"><span class="faculty-shortcut-icon">âŒ•</span><span><strong>Find a space</strong><small>Browse available campus resources</small></span><span class="faculty-shortcut-arrow">â†’</span></button>
        <button type="button" class="faculty-shortcut" onclick="go('bookEquipment')"><span class="faculty-shortcut-icon faculty-shortcut-icon-alt">âœ³</span><span><strong>Book equipment</strong><small>Reserve the equipment you need</small></span><span class="faculty-shortcut-arrow">â†’</span></button>
      </section>
    `;
    host.innerHTML = html;
  } catch (err) {
    host.innerHTML = `<div class="empty">Failed to load dashboard: ${esc(err.message)}</div>`;
  }
}

function formatScheduleDate(value) {
  const [year, month, day] = String(value || "").slice(0, 10).split("-").map(Number);
  if (!year || !month || !day) return "Date unavailable";
  const date = new Date(Date.UTC(year, month - 1, day, 12));
  return new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "UTC"
  }).format(date);
}

function formatScheduleTime(value) {
  const match = String(value || "").match(/[T ](\d{2}:\d{2})/);
  return match ? match[1] : "—";
}

function formatScheduleWindow(start, end) {
  const startDate = String(start || "").slice(0, 10);
  const endDate = String(end || "").slice(0, 10);
  const startLabel = startDate && startDate !== endDate
    ? `${formatScheduleDate(startDate)} ${formatScheduleTime(start)}`
    : formatScheduleTime(start);
  const endLabel = endDate && startDate !== endDate
    ? `${formatScheduleDate(endDate)} ${formatScheduleTime(end)}`
    : formatScheduleTime(end);
  return `${startLabel} – ${endLabel}`;
}

function renderScheduleBooking(booking, isToday) {
  const start = booking.start_time;
  const end = booking.end_time;
  const resources = (booking.resources || []).map(resource => `
    <div class="schedule-detail">
      <strong>${esc(resource.resource_name || "Campus resource")}</strong>
      ${resource.location ? `<span>${esc(resource.location)}</span>` : ""}
      <span>${formatScheduleWindow(resource.start_time, resource.end_time)}</span>
    </div>
  `).join("");
  const equipment = (booking.equipment || []).map(item => `
    <div class="schedule-detail">
      <strong>${esc(item.item_name || "Equipment")} × ${item.requested_quantity}</strong>
      ${item.location ? `<span>${esc(item.location)}</span>` : ""}
    </div>
  `).join("");
  const scheduleTime = resources
    ? ""
    : `<div class="schedule-detail"><span>${formatScheduleWindow(start, end)}</span></div>`;
  const dateLabel = isToday ? "" : `<div class="schedule-date">${esc(formatScheduleDate(start))}</div>`;

  return `
    <article class="schedule-booking">
      <div class="schedule-booking-head">
        <strong>Booking BK-${booking.booking_id}</strong>
        ${dateLabel}
      </div>
      <p>${esc(booking.purpose)}</p>
      <div class="schedule-details">${resources}${equipment}${scheduleTime}</div>
    </article>
  `;
}

async function renderMySchedule() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading your schedule...</div>`;

  try {
    const schedule = await api.get("/bookings/my/schedule");
    const todayBookings = schedule.today_bookings || [];
    const upcomingBookings = schedule.upcoming_bookings || [];
    host.innerHTML = `
      <section class="panel pad schedule-section">
        <h3>Today's Schedule</h3>
        ${todayBookings.length
          ? `<div class="schedule-bookings">${todayBookings.map(booking => renderScheduleBooking(booking, true)).join("")}</div>`
          : `<p class="schedule-empty">No approved bookings scheduled for today.</p>`}
      </section>
      <section class="panel pad schedule-section">
        <h3>Upcoming Schedule</h3>
        ${upcomingBookings.length
          ? `<div class="schedule-bookings">${upcomingBookings.map(booking => renderScheduleBooking(booking, false)).join("")}</div>`
          : `<p class="schedule-empty">No upcoming approved bookings.</p>`}
      </section>`;
  } catch (err) {
    host.innerHTML = `<div class="empty">Failed to load your schedule: ${esc(err.message)}</div>`;
  }
}

async function renderSettings() {
  const host = $("view");
  host.innerHTML = `<div class="empty">Loading system settings...</div>`;

  try {
    const s = await api.get("/reports/settings");
    const categoryOptions = (s.categories || []).map(category => `
      <option value="${esc(category)}" ${(s.approval_categories || []).includes(category) ? "selected" : ""}>${esc(category)}</option>
    `).join("");
    host.innerHTML = `
      <div class="panel pad">
        <h3>Booking rules and approval settings</h3>
        <form id="settingsForm" onsubmit="saveSettings(event)">
          <div class="form-grid">
            <label class="field">Academic year
              <input id="settingsAcademicYear" class="input" value="${esc(s.academic_year)}" pattern="\\d{4}-\\d{4}" required>
            </label>
            <label class="field">Maximum advance booking (days)
              <input id="settingsBookingWindow" class="input" type="number" min="1" max="365" value="${s.booking_window_days}" required>
            </label>
            <label class="field">Minimum booking duration (minutes)
              <input id="settingsMinDuration" class="input" type="number" min="15" max="1440" value="${s.min_booking_minutes}" required>
            </label>
            <label class="field">Maximum booking duration (minutes)
              <input id="settingsMaxDuration" class="input" type="number" min="15" max="1440" value="${s.max_booking_minutes}" required>
            </label>
            <label class="field">Cancellation cutoff (hours; 0 disables)
              <input id="settingsCancelCutoff" class="input" type="number" min="0" max="720" value="${s.cancellation_cutoff_hours}" required>
            </label>
            <label class="field">Approval workflow
              <select id="settingsApprovalMode" class="input">
                <option value="Manual" ${s.approval_mode === "Manual" ? "selected" : ""}>Manual approval for all bookings</option>
                <option value="ByCategory" ${s.approval_mode === "ByCategory" ? "selected" : ""}>Require approval only for selected categories</option>
              </select>
            </label>
            <label class="field">Categories requiring manual approval
              <select id="settingsApprovalCategories" class="input" multiple size="5">${categoryOptions}</select>
              <span class="muted">In category-based mode, categories not selected are automatically approved.</span>
            </label>
          </div>
          <label class="check-row" style="display:flex;gap:8px;align-items:center;margin:14px 0;">
            <input id="settingsTimetableEnforcement" type="checkbox" ${s.timetable_enforcement ? "checked" : ""}>
            Enforce recurring timetable conflicts for ${esc(s.academic_year)}
          </label>
          <div class="actions">
            <button class="btn primary" type="submit">Save booking rules</button>
            <span class="pill neutral">${s.timetable_entries_active} timetable records in configured year</span>
          </div>
        </form>
        <hr>
        <div class="setting-row">
          <div><div class="lbl">Database</div><div class="desc">${esc(s.database_name)} · pool ${esc(s.database_pool)} (${s.database_pool_size})</div></div>
          <span class="pill ok">Connected</span>
        </div>
        <div class="setting-row">
          <div><div class="lbl">Authentication</div><div class="desc">JWT token validity: ${s.token_expire_minutes} minutes · ${esc(s.environment)}</div></div>
          <span class="pill neutral">Session secured</span>
        </div>
      </div>
    `;
  } catch (err) {
    host.innerHTML = `<div class="empty">Failed to load system settings: ${esc(err.message)}</div>`;
  }
}

async function saveSettings(event) {
  event.preventDefault();
  const approvalCategories = Array.from($("settingsApprovalCategories").selectedOptions).map(option => option.value);
  const payload = {
    academic_year: $("settingsAcademicYear").value.trim(),
    timetable_enforcement: $("settingsTimetableEnforcement").checked,
    booking_window_days: Number($("settingsBookingWindow").value),
    approval_mode: $("settingsApprovalMode").value,
    approval_categories: approvalCategories,
    min_booking_minutes: Number($("settingsMinDuration").value),
    max_booking_minutes: Number($("settingsMaxDuration").value),
    cancellation_cutoff_hours: Number($("settingsCancelCutoff").value)
  };
  try {
    await api.put("/reports/settings", payload);
    toast("Booking rules saved and are now active.", "ok");
    await renderSettings();
  } catch (err) {
    toast("Could not save booking rules: " + err.message, "err");
  }
}

// Global window registrations for modular accessibility
window.renderAdminDash = renderAdminDash;
window.setDashboardRange = setDashboardRange;
window.renderReports = renderReports;
window.renderAudit = renderAudit;
window.filterAuditTable = filterAuditTable;
window.renderFacultyDash = renderFacultyDash;
window.renderMySchedule = renderMySchedule;
window.renderSettings = renderSettings;
window.saveSettings = saveSettings;
