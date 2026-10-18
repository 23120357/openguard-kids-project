"use strict";
let csrf = "";
let currentPolicy = null;
let currentFiltering = null;
let filteringDirty = false;
let filteringSequence = 0;
let observedApps = [];
let appDrafts = {app_allow: [], app_block: []};
let appCatalogView = 'featured';
let reportSequence = 0;
let appReportSequence = 0;
const REPORT_REFRESH_MS = 60 * 1000;
let reportCache = {key: '', loadedAt: 0};
let appReportCache = {key: '', loadedAt: 0};
const domainLists = ['domain_block', 'domain_allow', 'safety_domains'];
const bulkDomainLists = ['domain_block', 'domain_allow', 'safety_domains'];
const rowDomainLists = [];
const mandatorySafetyDomain = 'tongdai111.vn';
let domainDrafts = {domain_block: [], domain_allow: [], safety_domains: []};
const dashboardTabs = ['overview', 'report', 'time-policy', 'filtering', 'activity'];
let activeDashboardTab = 'overview';
let activityOffset = 0;
let activitySequence = 0;
let childProfiles = [];
let liveEvents = null;
let liveRefreshTimer = null;
const pendingLiveKinds = new Set();
const deviceGrantMinutes = new Map();
const el = (id) => document.getElementById(id);
const tell = (message) => { el("message").textContent = message; };
const dayNames = ["Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy", "Chủ nhật"];
const formatDuration = seconds => Math.floor(seconds / 60) + " phút " + String(seconds % 60).padStart(2, "0") + " giây";
const formatChartDuration = seconds => Math.floor(seconds / 3600) + ' giờ ' + String(Math.floor(seconds % 3600 / 60)).padStart(2, '0') + ' phút' + (seconds % 60 ? ' ' + String(seconds % 60).padStart(2, '0') + ' giây' : '');

function updateDeviceCountdowns() {
  document.querySelectorAll(".device-countdown").forEach(line => {
    const elapsedSinceRender = Math.max(0, performance.now() / 1000 - Number(line.dataset.renderedAt));
    const running = line.dataset.running === "true" && elapsedSinceRender < Number(line.dataset.freshFor);
    const elapsed = running ? Math.floor(elapsedSinceRender) : 0;
    const used = Number(line.dataset.usedSeconds);
    const remaining = Number(line.dataset.remainingSeconds);
    line.querySelector(".device-used").textContent = formatDuration(used + elapsed);
    line.querySelector(".device-remaining").textContent = formatDuration(Math.max(0, remaining - elapsed));
  });
}

function buildScheduleEditor() {
  const rows = dayNames.map((name, index) => {
    const row = document.createElement("div"); row.className = "schedule-row";
    const enabled = document.createElement("input"); enabled.type = "checkbox";
    enabled.name = "day_enabled_" + index; enabled.defaultChecked = true;
    const day = document.createElement("label"); day.className = "schedule-day";
    const label = document.createElement("span"); label.textContent = name;
    day.append(enabled, label);
    const ranges = document.createElement("div"); ranges.className = "schedule-ranges";
    const add = document.createElement("button"); add.type = "button";
    add.textContent = "Thêm khoảng"; add.className = "secondary";
    add.addEventListener("click", () => {
      enabled.checked = true;
      appendScheduleRange(ranges, index);
    });
    row.append(day, ranges, add);
    appendScheduleRange(ranges, index);
    return row;
  });
  el("schedule-grid").replaceChildren(...rows);
  el("schedule-grid").addEventListener("change", () => {
    if (el("schedule-error").textContent) validateSchedule(el("policy-form"), false);
  });
}

let scheduleRangeId = 0;
function appendScheduleRange(container, dayIndex, start = 0, end = 48) {
  const controls = document.createElement("div"); controls.className = "schedule-controls";
  const prefix = "range_" + scheduleRangeId++;
  controls.dataset.start = prefix + "_start";
  controls.dataset.end = prefix + "_end";
  const separator = document.createElement("span"); separator.textContent = "đến";
  const remove = document.createElement("button"); remove.type = "button";
  remove.textContent = "Xóa khoảng"; remove.className = "secondary";
  remove.setAttribute("aria-label", "Xóa khoảng giờ " + dayNames[dayIndex]);
  remove.addEventListener("click", () => {
    controls.remove();
    if (!container.children.length) {
      el("policy-form").elements["day_enabled_" + dayIndex].checked = false;
    }
    validateSchedule(el("policy-form"), false);
  });
  controls.append(
    scheduleTimeSelect(controls.dataset.start, dayNames[dayIndex] + ", bắt đầu"),
    separator,
    scheduleTimeSelect(controls.dataset.end, dayNames[dayIndex] + ", kết thúc"),
    remove,
  );
  container.append(controls);
  [start, end].forEach((slot, index) => {
    const selects = controls.querySelectorAll("select");
    selects[index * 2].value = String(Math.floor(slot / 2) % 24).padStart(2, "0");
    selects[index * 2 + 1].value = slot % 2 ? "30" : "00";
  });
}

function scheduleRanges(form, index) {
  return Array.from(el("schedule-grid").children[index].querySelectorAll(".schedule-controls"), range => [
    timeToSlot(scheduleTimeFromForm(form, range.dataset.start)),
    timeToSlot(scheduleTimeFromForm(form, range.dataset.end), true),
  ]);
}

function scheduleTimeSelect(name, label) {
  const group = document.createElement("span"); group.className = "schedule-time";
  const hour = document.createElement("select"); hour.name = name + "_hour";
  hour.setAttribute("aria-label", label + ", giờ");
  hour.replaceChildren(...Array.from({length: 24}, (_, value) => {
    const text = String(value).padStart(2, "0"); return new Option(text, text);
  }));
  const minute = document.createElement("select"); minute.name = name + "_minute";
  minute.setAttribute("aria-label", label + ", phút");
  minute.replaceChildren(new Option("00", "00"), new Option("30", "30"));
  const colon = document.createElement("span"); colon.textContent = ":";
  group.append(hour, colon, minute);
  return group;
}

function timeToSlot(value, isEnd = false) {
  if (isEnd && value === "00:00") return 48;
  if (!/^([01]\d|2[0-3]):(00|30)$/.test(value)) throw new Error("Giờ phải ở định dạng 24h, phút là 00 hoặc 30.");
  const [hour, minute] = value.split(":").map(Number);
  return hour * 2 + minute / 30;
}

function scheduleTimeFromForm(form, name) {
  return form.elements[name + "_hour"].value + ":" + form.elements[name + "_minute"].value;
}

function setScheduleTime(form, name, value) {
  const [hour, minute] = value.split(":");
  form.elements[name + "_hour"].value = hour;
  form.elements[name + "_minute"].value = minute;
}

function clearScheduleValidation() {
  el("schedule-error").textContent = "";
  document.querySelectorAll(".schedule-row--invalid").forEach(row => {
    row.classList.remove("schedule-row--invalid");
    row.querySelectorAll("select").forEach(select => {
      select.removeAttribute("aria-invalid");
      select.removeAttribute("aria-describedby");
    });
  });
}

function validateSchedule(form, focusFirst = true) {
  clearScheduleValidation();
  const invalidDays = [];
  dayNames.forEach((day, index) => {
    if (!form.elements["day_enabled_" + index].checked) return;
    const ranges = scheduleRanges(form, index);
    if (ranges.length && ranges.every(([start, end]) => end > start)) return;
    const row = el("schedule-grid").children[index];
    row.classList.add("schedule-row--invalid");
    row.querySelectorAll("select").forEach(select => {
      select.setAttribute("aria-invalid", "true");
      select.setAttribute("aria-describedby", "schedule-error");
    });
    invalidDays.push(day);
  });
  if (!invalidDays.length) return true;
  el("schedule-error").textContent =
    "Giờ sử dụng không hợp lệ ở " + invalidDays.join(", ") +
    ": cần ít nhất một khoảng và giờ kết thúc phải sau giờ bắt đầu.";
  if (focusFirst) document.querySelector(".schedule-row--invalid select")?.focus();
  return false;
}

function scheduleFromForm(form) {
  if (!validateSchedule(form)) throw new Error(el("schedule-error").textContent);
  return dayNames.map((_, index) => {
    if (!form.elements["day_enabled_" + index].checked) return "0".repeat(48);
    const ranges = scheduleRanges(form, index);
    return Array.from({length: 48}, (_, slot) => ranges.some(([start, end]) => slot >= start && slot < end) ? "1" : "0").join("");
  });
}

function showSchedule(schedule) {
  clearScheduleValidation();
  schedule.forEach((slots, index) => {
    const enabled = slots.includes("1");
    el("policy-form").elements["day_enabled_" + index].checked = enabled;
    const container = el("schedule-grid").children[index].querySelector(".schedule-ranges");
    container.replaceChildren();
    for (let slot = 0; slot < 48;) {
      if (slots[slot] !== "1") { slot++; continue; }
      const start = slot;
      while (slot < 48 && slots[slot] === "1") slot++;
      appendScheduleRange(container, index, start, slot);
    }
    if (!enabled) appendScheduleRange(container, index);
  });
}

async function api(path, method = "GET", body) {
  const response = await fetch("/api" + path, {
    method, credentials: "same-origin",
    cache: method === "GET" ? "no-store" : "default",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return null;
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; }
  catch (_error) { /* A proxy or unhandled server error may return plain text. */ }
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/login") showLogin();
    throw new Error(
      typeof data?.detail === "string"
        ? data.detail
        : "Máy chủ gặp lỗi (HTTP " + response.status + "). Hãy thử lại.",
    );
  }
  return data;
}
function showLogin() {
  document.body.classList.remove("workspace-active");
  if (liveEvents) { liveEvents.close(); liveEvents = null; }
  if (liveRefreshTimer) { clearTimeout(liveRefreshTimer); liveRefreshTimer = null; }
  pendingLiveKinds.clear();
  csrf = ""; currentPolicy = null; childProfiles = [];
  currentFiltering = null; activityOffset = 0; activitySequence++;
  observedApps = []; appDrafts = {app_allow: [], app_block: []};
  reportSequence++;
  appReportSequence++;
  reportCache = {key: '', loadedAt: 0};
  appReportCache = {key: '', loadedAt: 0};
  clearReport();
  filteringDirty = false;
  domainDrafts = {domain_block: [], domain_allow: [], safety_domains: []};
  renderDomainLists();
  selectDashboardTab('overview');
  el("workspace").hidden = true; el("login-panel").hidden = false;
  ["devices", "audit", "child-select", "pairing-code", "identity", "activity-rows"].forEach(id => el(id).replaceChildren());
  el('filtering-form').reset(); el('deletion-status').textContent = ''; el('activity-empty').textContent = '';
  el("policy-form").reset(); el("code-form").reset();
}
async function loadPolicy() {
  currentPolicy = null;
  const id = el("child-select").value;
  if (!id) { currentFiltering = null; return; }
  const policy = await api("/children/" + encodeURIComponent(id) + "/policy");
  if (el("child-select").value !== id) return;
  currentPolicy = policy;
  el("policy-form").elements.enabled.checked = policy.enabled;
  el("policy-form").elements.weekday_minutes.value = policy.weekday_minutes;
  el("policy-form").elements.weekend_minutes.value = policy.weekend_minutes;
  el("policy-version").textContent = "Phiên bản " + policy.version;
  showSchedule(policy.schedule);
}
async function refreshSelectedChildTab() {
  const childId = el("child-select").value;
  if (!childId) return;
  if (activeDashboardTab === 'time-policy') await loadPolicy();
  else if (activeDashboardTab === 'filtering') await loadFiltering(childId);
  else if (activeDashboardTab === 'activity') await refreshActivity();
  else if (activeDashboardTab === 'report') await refreshReport();
}
async function loadChildren(preferredId = null) {
  const rows = await api("/children");
  childProfiles = rows;
  const previousId = el("child-select").value;
  const oldId = preferredId || previousId;
  el("child-select").replaceChildren(...rows.map(row => new Option(row.display_name, row.id)));
  if (rows.some(row => row.id === oldId)) el("child-select").value = oldId;
  if (el("child-select").value !== previousId) {
    el("pairing-code").textContent = "";
    el("code-form").reset();
  }
  const selected = rows.find(row => row.id === el("child-select").value);
  if (el('child-select').value !== oldId) activityOffset = 0;
  el("child-pin-status").textContent = selected ? (selected.has_pin ? "PIN đã được thiết lập." : "Hồ sơ cũ chưa có PIN; hãy tạo PIN trước khi đăng nhập trên máy trẻ.") : "";
  await refreshSelectedChildTab();
}
function renderList(id, lines, empty) {
  el(id).replaceChildren(...(lines.length ? lines : [empty]).map(line => {
    const li = document.createElement("li"); li.textContent = line; return li;
  }));
}
function auditSchedule(row) {
  if (typeof row !== 'string') return 'chưa đặt';
  const ranges = [];
  for (let start = 0; start < 48;) {
    if (row[start] !== '1') { start++; continue; }
    let end = start + 1; while (end < 48 && row[end] === '1') end++;
    const clock = slot => slot === 48 ? '24:00' : String(Math.floor(slot / 2)).padStart(2, '0') + ':' + (slot % 2 ? '30' : '00');
    ranges.push(clock(start) + '–' + clock(end)); start = end;
  }
  return ranges.join(', ') || 'không cho dùng';
}
function formatAuditEntry(a) {
  const old = a.old_value || {}, next = a.new_value || {}, changes = [];
  const labels = {enabled:'Kiểm soát', dns_proxy_enabled:'DNS proxy', weekday_minutes:'Ngày thường', weekend_minutes:'Cuối tuần', domain_mode:'Quy tắc web', app_mode:'Quy tắc ứng dụng'};
  const value = (key, item) => key === 'enabled' ? (item ? 'bật' : 'tắt') : key.endsWith('_minutes') ? item + ' phút' : key.endsWith('_mode') ? ({blocklist:'chặn theo danh sách',allowlist:'chỉ cho phép danh sách'}[item] || item) : String(item);
  for (const key of Object.keys(labels)) {
    if (key in next && old[key] !== next[key]) changes.push(labels[key] + ': ' + (key in old ? value(key, old[key]) + ' → ' : '') + value(key, next[key]));
  }
  for (const [key, label] of Object.entries({domain_block:'web bị chặn', domain_allow:'web được phép', safety_domains:'web an toàn', app_block:'ứng dụng bị chặn', app_allow:'ứng dụng được phép'})) {
    const describe = item => typeof item === 'string' ? item : item.name;
    const before = new Set((old[key] || []).map(describe)), after = new Set((next[key] || []).map(describe));
    for (const item of after) if (!before.has(item)) changes.push('Thêm ' + label + ': ' + item);
    for (const item of before) if (!after.has(item)) changes.push('Xóa ' + label + ': ' + item);
  }
  if (Array.isArray(next.schedule)) next.schedule.forEach((row, index) => {
    if (row !== (old.schedule || [])[index]) changes.push(dayNames[index] + ': ' + auditSchedule((old.schedule || [])[index]) + ' → ' + auditSchedule(row));
  });
  if (next.type) changes.push('Lệnh: ' + ({lock_now:'khóa máy ngay',add_time:'cộng thêm giờ'}[next.type] || next.type));
  if (next.payload?.minutes) changes.push('Cộng ' + next.payload.minutes + ' phút');
  if (next.minutes && a.action !== 'policy_updated') changes.push(next.minutes + ' phút');
  if (next.requester) changes.push('Người gửi: ' + next.requester);
  if (next.status) changes.push('Trạng thái: ' + ({pending:'đang chờ',approved:'đã đồng ý',rejected:'đã từ chối',acknowledged:'đã xác nhận'}[next.status] || next.status));
  if (a.action === 'child_pin_changed') changes.push('PIN 6 số đã đổi');
  if (a.action === 'enrollment_consent') changes.push('Đã đồng ý ghép thiết bị');
  const action = ({policy_updated:'Chính sách thời gian',filtering_updated:'Kiểm soát web và ứng dụng',enrollment_consent:'Ghép thiết bị',emergency_command_created:'Lệnh thiết bị',emergency_command_acknowledged:'Thiết bị xác nhận lệnh',time_requested:'Yêu cầu thêm giờ',time_request_decided:'Trả lời yêu cầu thêm giờ',child_pin_changed:'PIN hồ sơ',device_revoked:'Thu hồi thiết bị'}[a.action] || a.action);
  const child = childProfiles.find(item => item.id === a.child_id);
  return new Date(a.ts * 1000).toLocaleString('vi-VN') + ' · ' + action + (child ? ' · ' + child.display_name : '') + (a.actor ? ' · ' + a.actor : '') + (changes.length ? ': ' + changes.join('; ') : '');
}
async function refreshStatus() {
  const [devices, audits, requests] = await Promise.all([
    api("/devices"), api("/audit"), api("/time-requests")
  ]);
  const deviceItems = devices.length ? devices.map(d => {
    const li = document.createElement("li");
    const state = d.revoked ? "offline" : !d.online ? "offline" : d.active_user ? "active" : "online";
    li.className = "device-card device-card--" + state;
    const title = document.createElement("h3"); title.textContent = d.display_name;
    const details = document.createElement("div"); details.className = "device-details";
    const detail = (label, value) => {
      const line = document.createElement("div"); line.className = "device-detail";
      const name = document.createElement("strong"); name.textContent = label + ": ";
      const content = document.createElement("span"); content.textContent = value;
      line.append(name, content); details.append(line); return content;
    };
    detail("Trạng thái", d.revoked ? "Đã thu hồi quyền truy cập" : d.online ? "Trực tuyến" : "Ngoại tuyến");
    detail("Phiên bản chính sách", "v" + d.policy_version);
    detail("Lần kết nối gần nhất", d.last_seen ? new Date(d.last_seen * 1000).toLocaleString("vi-VN") : "Chưa gửi heartbeat");
    detail("Đang dùng", d.active_user || "Chưa đăng nhập");
    if (d.active_since) detail("Bắt đầu phiên", new Date(d.active_since * 1000).toLocaleString("vi-VN"));
    if (d.active_child_id && d.used_seconds != null && d.remaining_seconds != null) {
      const timeLine = document.createElement("div"); timeLine.className = "device-countdown";
      const reportAge = d.time_status_at ? Math.max(0, d.server_time - d.time_status_at) : Infinity;
      const running = d.online && d.active_usage && reportAge < 10;
      const elapsedOnServer = running ? Math.floor(reportAge) : 0;
      timeLine.dataset.usedSeconds = d.used_seconds + elapsedOnServer;
      timeLine.dataset.remainingSeconds = Math.max(0, d.remaining_seconds - elapsedOnServer);
      timeLine.dataset.renderedAt = performance.now() / 1000;
      timeLine.dataset.freshFor = Math.max(0, 10 - reportAge);
      timeLine.dataset.running = String(running);
      const used = document.createElement("div"); used.className = "device-detail";
      const usedLabel = document.createElement("strong"); usedLabel.textContent = "Đã dùng hôm nay: ";
      const usedValue = document.createElement("span"); usedValue.className = "device-used";
      used.append(usedLabel, usedValue);
      const remaining = document.createElement("div"); remaining.className = "device-detail";
      const remainingLabel = document.createElement("strong"); remainingLabel.textContent = "Còn lại hôm nay: ";
      const remainingValue = document.createElement("span"); remainingValue.className = "device-remaining";
      remaining.append(remainingLabel, remainingValue);
      timeLine.append(used, remaining); details.append(timeLine);
    } else if (!("time_status_at" in d)) {
      detail("Đã dùng hôm nay", "Server đang chạy bản cũ; hãy khởi động lại server");
      detail("Còn lại hôm nay", "Chưa thể đồng bộ");
    } else if (d.active_child_id) {
      detail("Đã dùng hôm nay", "Agent chưa gửi số liệu; hãy khởi động lại service");
      detail("Còn lại hôm nay", "Chưa thể đồng bộ");
    } else {
      detail("Đã dùng hôm nay", "Chưa có phiên sử dụng");
      detail("Còn lại hôm nay", "Chưa có dữ liệu");
    }
    const actions = document.createElement("div"); actions.className = "device-actions";
    [["Khóa ngay", "lock_now"]].forEach(([label, command]) => {
      const button = document.createElement("button"); button.type = "button"; button.textContent = label;
      button.disabled = d.revoked;
      button.addEventListener("click", () => sendCommand(d.id, command, button)); actions.append(button);
    });
    const minutes = document.createElement("input"); minutes.type = "number"; minutes.min = "1";
    minutes.max = "120"; minutes.value = deviceGrantMinutes.get(d.id) || "15"; minutes.className = "grant-minutes";
    minutes.setAttribute("aria-label", "Số phút cộng thêm hôm nay");
    minutes.addEventListener("input", () => deviceGrantMinutes.set(d.id, minutes.value));
    const grant = document.createElement("button"); grant.type = "button"; grant.textContent = "Cộng phút";
    grant.disabled = !d.active_child_id || d.revoked;
    grant.addEventListener("click", () => sendCommand(d.id, "add_time", grant, Number(minutes.value)));
    actions.append(minutes, grant);
    if (!d.revoked) {
      const revoke = document.createElement("button"); revoke.type = "button";
      revoke.className = "secondary"; revoke.textContent = "Thu hồi thiết bị";
      revoke.addEventListener("click", () => revokeDevice(d.id, d.display_name, revoke));
      actions.append(revoke);
    }
    li.append(title, details, actions); return li;
  }) : [Object.assign(document.createElement("li"), {textContent: "Chưa có thiết bị. Hãy tạo mã ghép đôi."})];
  el("devices").replaceChildren(...deviceItems);
  updateDeviceCountdowns();
  renderList("audit", audits.slice(0, 10).map(formatAuditEntry), "Chưa có thay đổi.");
  const requestItems = requests.length ? requests.map(request => {
    const li = document.createElement("li");
    const detail = document.createElement("span");
    const created = new Date(request.created_at * 1000);
    const clock = created.toLocaleTimeString("vi-VN", {hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false});
    const date = created.getDate() + "/" + (created.getMonth() + 1) + "/" + created.getFullYear();
    detail.textContent = clock + " " + date +
      " · " + request.requester + " xin " + request.minutes + " phút · Máy " +
      request.device_name + " · " +
      (request.status === "pending" ? "Đang chờ" : request.status === "approved" ? "Đã duyệt" : "Đã từ chối");
    li.append(detail);
    if (request.status === "pending") {
      const actions = document.createElement("div"); actions.className = "device-actions";
      [["Duyệt và cộng giờ", true], ["Từ chối", false]].forEach(([label, approved]) => {
        const button = document.createElement("button"); button.type = "button";
        button.textContent = label; if (!approved) button.className = "secondary";
        button.addEventListener("click", () => decideTimeRequest(request.id, approved, button));
        actions.append(button);
      });
      li.append(actions);
    }
    return li;
  }) : [Object.assign(document.createElement("li"), {textContent: "Chưa có yêu cầu."})];
  el("time-requests").replaceChildren(...requestItems);
}
function scheduleLiveRefresh(kind = "status") {
  if (!csrf) return;
  pendingLiveKinds.add(kind);
  if (liveRefreshTimer) return;
  liveRefreshTimer = setTimeout(async () => {
    liveRefreshTimer = null;
    const kinds = new Set(pendingLiveKinds);
    pendingLiveKinds.clear();
    try {
      if (kinds.has("children")) await loadChildren();
      else if (kinds.has("policy") || kinds.has("activity")) await refreshSelectedChildTab();
      await refreshStatus();
    } catch (error) { tell(error.message); }
  }, 100);
}
function connectLiveUpdates() {
  if (liveEvents) liveEvents.close();
  if (!("EventSource" in window)) return;
  liveEvents = new EventSource("/api/parent/events");
  liveEvents.addEventListener("change", event => {
    try { scheduleLiveRefresh(JSON.parse(event.data).kind || "status"); }
    catch (_error) { scheduleLiveRefresh(); }
  });
}
async function sendCommand(deviceId, command, button, minutes = 15) {
  button.disabled = true;
  try {
    const body = {command_type: command};
    if (command === "add_time") {
      if (!Number.isInteger(minutes) || minutes < 1 || minutes > 120) throw new Error("Chọn từ 1 đến 120 phút.");
      body.minutes = minutes;
    }
    const result = await api("/devices/" + encodeURIComponent(deviceId) + "/commands", "POST", body);
    tell(result.realtime_delivered ? "Agent đã nhận lệnh qua kênh khẩn." : "Đã xếp hàng; agent sẽ nhận ở lần kết nối tiếp theo.");
    await refreshStatus();
  } catch (error) { tell(error.message); } finally { button.disabled = false; }
}
async function revokeDevice(deviceId, deviceName, button) {
  if (!window.confirm("Thu hồi quyền của máy " + deviceName + "? Máy sẽ phải ghép đôi lại để kết nối.")) return;
  button.disabled = true;
  try {
    await api("/devices/" + encodeURIComponent(deviceId) + "/revoke", "POST", {});
    tell("Đã thu hồi thiết bị. Access token và refresh token cũ không còn hiệu lực.");
    await refreshStatus();
  } catch (error) { tell(error.message); } finally { button.disabled = false; }
}
async function decideTimeRequest(requestId, approved, button) {
  button.disabled = true;
  try {
    const result = await api("/time-requests/" + encodeURIComponent(requestId) + "/decision", "POST", {approved});
    tell(approved ? (result.realtime_delivered ? "Đã duyệt và cộng giờ ngay." : "Đã duyệt; giờ sẽ được cộng khi thiết bị kết nối.") : "Đã từ chối yêu cầu.");
    await refreshStatus();
  } catch (error) { tell(error.message); } finally { button.disabled = false; }
}
async function enterWorkspace(user) {
  csrf = user.csrf_token; el("identity").textContent = user.email;
  document.body.classList.add("workspace-active");
  el("login-panel").hidden = true; el("workspace").hidden = false;
  await loadChildren(); await refreshStatus();
  connectLiveUpdates();
}
function form(id, handler) {
  el(id).addEventListener("submit", async (event) => {
    event.preventDefault(); tell("");
    const button = event.submitter || event.target.querySelector('button[type="submit"]') || event.target.querySelector("button");
    button.disabled = true;
    button.classList.add("is-loading");
    button.setAttribute("aria-busy", "true");
    try { await handler(new FormData(event.target)); }
    catch (error) { tell(error.message); }
    finally {
      button.disabled = false;
      button.classList.remove("is-loading");
      button.removeAttribute("aria-busy");
    }
  });
}
form("login-form", async data => {
  const user = await api("/auth/login", "POST", Object.fromEntries(data));
  el("login-form").reset(); await enterWorkspace(user);
});
form("child-form", async data => {
  if (data.get("pin") !== data.get("pin_confirm")) throw new Error("Hai mã PIN không khớp.");
  const created = await api("/children", "POST", {display_name: data.get("display_name"), pin: data.get("pin")});
  el("child-form").reset(); await loadChildren(created.id); tell("Đã tạo hồ sơ.");
});
form("pin-form", async data => {
  const childId = el("child-select").value;
  if (!childId) throw new Error("Hãy chọn hồ sơ của con.");
  if (data.get("pin") !== data.get("pin_confirm")) throw new Error("Hai mã PIN không khớp.");
  await api("/children/" + encodeURIComponent(childId) + "/pin", "PUT", {pin: data.get("pin")});
  el("pin-form").reset(); await loadChildren(); tell("Đã lưu PIN. Máy trẻ sẽ nhận trong lần đồng bộ tiếp theo.");
});
form("code-form", async () => {
  const child_id = el("child-select").value;
  if (!child_id) throw new Error("Hãy tạo hồ sơ của con trước.");
  const result = await api("/enrollment-codes", "POST", { child_id, consent: true });
  el("pairing-code").textContent = result.code; await refreshStatus();
});
form("delete-account-form", async data => {
  const confirmed = window.confirm(
    "Xóa vĩnh viễn tài khoản phụ huynh, tất cả hồ sơ trẻ và mọi thiết bị đã ghép? Thao tác này không thể hoàn tác."
  );
  if (!confirmed) return;
  await api("/account", "DELETE", {password: data.get("password")});
  el("delete-account-form").reset();
  showLogin();
  tell("Tài khoản, hồ sơ trẻ và thiết bị đã được xóa vĩnh viễn.");
});
form("policy-form", async data => {
  if (!currentPolicy) throw new Error("Hãy chọn hồ sơ của con.");
  const result = await api("/children/" + currentPolicy.child_id + "/policy", "PUT", {
    expected_version: currentPolicy.version,
    enabled: data.get("enabled") === "on",
    weekday_minutes: Number(data.get("weekday_minutes")),
    weekend_minutes: Number(data.get("weekend_minutes")),
    schedule: scheduleFromForm(el("policy-form")),
  });
  currentPolicy = result;
  el("policy-version").textContent = "Phiên bản " + result.version;
  tell("Đã lưu. Agent sẽ nhận cấu hình ở heartbeat tiếp theo.");
  await refreshStatus();
});
el("child-select").addEventListener("change", () => {
  clearReport();
  el("pairing-code").textContent = "";
  el("code-form").reset();
  currentPolicy = null;
  currentFiltering = null;
  activityOffset = 0;
  activitySequence++;
  el('activity-rows').replaceChildren();
  const selected = childProfiles.find(row => row.id === el("child-select").value);
  el("child-pin-status").textContent = selected ? (selected.has_pin ? "PIN đã được thiết lập." : "Hồ sơ cũ chưa có PIN; hãy tạo PIN trước khi đăng nhập trên máy trẻ.") : "";
  refreshSelectedChildTab().catch(e => tell(e.message));
});
el("logout").addEventListener("click", async () => {
  try { await api("/auth/logout", "POST", {}); showLogin(); tell(""); }
  catch (e) { tell(e.message); }
});
setInterval(() => { if (csrf) scheduleLiveRefresh(); }, 10000);
setInterval(updateDeviceCountdowns, 1000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && csrf) scheduleLiveRefresh();
});
buildScheduleEditor();
api("/auth/me").then(enterWorkspace).catch(() => showLogin());

async function loadFiltering(childId, force = false) {
  if (el('child-select').value !== childId) return;
  if (!force && filteringDirty && currentFiltering?.child_id === childId) return;
  const sequence = ++filteringSequence;
  if (currentFiltering?.child_id !== childId) currentFiltering = null;
  const [policy, catalog] = await Promise.all([
    api('/children/' + encodeURIComponent(childId) + '/filtering'),
    api('/children/' + encodeURIComponent(childId) + '/observed-apps'),
  ]);
  policy.safety_domains = [...new Set(
    (policy.safety_domains || []).filter(domain => domain !== '111.vn').concat(mandatorySafetyDomain)
  )].sort();
  if (!csrf || sequence !== filteringSequence || el('child-select').value !== childId) return;
  if (!force && filteringDirty && currentFiltering?.child_id === childId) return;
  if (force || JSON.stringify(currentFiltering) !== JSON.stringify(policy)) clearDomainInspection();
  const changedProfile = currentFiltering?.child_id !== childId;
  currentFiltering = policy;
  filteringDirty = false;
  const fields = el('filtering-form').elements;
  fields.enabled.checked = policy.enabled;
  fields.dns_proxy_enabled.checked = policy.dns_proxy_enabled !== false;
  updateAppControlWarning();
  fields.safe_search.checked = policy.safe_search !== false;
  ['domain_mode', 'app_mode'].forEach(key => { fields[key].value = policy[key]; });
  domainLists.forEach(key => { domainDrafts[key] = [...policy[key]]; });
  bulkDomainLists.forEach(key => { el(key + '-editor').value = domainDrafts[key].join('\n'); el(key + '-search').value = ''; });
  rowDomainLists.forEach(key => { el(key + '-new').value = ''; });
  renderDomainLists();
  observedApps = catalog.items || [];
  appDrafts = {app_allow: policy.app_allow.map(rule => ({...rule})), app_block: policy.app_block.map(rule => ({...rule}))};
  el('app-search').value = '';
  appCatalogView = 'featured';
  document.querySelectorAll('[data-app-view]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.appView === appCatalogView));
  });
  el('system-apps-section').open = false;
  renderAppCatalog();
  loadCategoryCatalog().catch(error => { el('category-catalog-status').textContent = 'Không tải được danh sách: ' + error.message; });
}

function appRuleState(sha256) {
  if (appDrafts.app_block.some(rule => rule.sha256 === sha256)) return 'block';
  if (appDrafts.app_allow.some(rule => rule.sha256 === sha256)) return 'allow';
  return 'default';
}

function setAppRule(app, action) {
  for (const key of ['app_allow', 'app_block']) {
    appDrafts[key] = appDrafts[key].filter(rule => rule.sha256 !== app.sha256);
  }
  if (action === 'allow') appDrafts.app_allow.push({name: app.name, sha256: app.sha256});
  if (action === 'block') appDrafts.app_block.push({name: app.name, sha256: app.sha256});
  markFilteringDirty();
  updateAppControlWarning();
  renderAppCatalog();
}

function updateAppControlWarning() {
  const enabled = el('filtering-form').elements.enabled.checked;
  el('app-control-warning').hidden = enabled;
}

el('enable-filtering-from-apps').addEventListener('click', () => {
  const enabled = el('filtering-form').elements.enabled;
  enabled.checked = true;
  markFilteringDirty();
  updateAppControlWarning();
  enabled.focus();
});

const knownAppCatalog = {
  'chrome.exe': {label:'Google Chrome', icon:'', tone:'chrome'},
  'msedge.exe': {label:'Microsoft Edge', icon:'e', tone:'edge'},
  'firefox.exe': {label:'Mozilla Firefox', icon:'F', tone:'firefox'},
  'zalo.exe': {label:'Zalo', icon:'Z', tone:'zalo'},
  'discord.exe': {label:'Discord', icon:'D', tone:'discord'},
  'steam.exe': {label:'Steam', icon:'S', tone:'steam'},
  'robloxplayerbeta.exe': {label:'Roblox', icon:'◇', tone:'roblox'},
  'spotify.exe': {label:'Spotify', icon:'≋', tone:'spotify'},
  'chatgpt.exe': {label:'ChatGPT', icon:'✦', tone:'chatgpt'},
  'code.exe': {label:'Visual Studio Code', icon:'⌁', tone:'vscode'},
  'teams.exe': {label:'Microsoft Teams', icon:'T', tone:'teams'},
  'zoom.exe': {label:'Zoom', icon:'Z', tone:'zoom'},
};

const systemAppNames = new Set([
  'cmd.exe', 'powershell.exe', 'pwsh.exe', 'conhost.exe', 'node.exe', 'node_repl.exe',
  'unsecapp.exe', 'widgetservice.exe', 'crossdeviceresume.exe', 'runtimebroker.exe',
  'svchost.exe', 'taskhostw.exe', 'dllhost.exe', 'searchhost.exe', 'shellhost.exe',
  'startmenuexperiencehost.exe', 'applicationframehost.exe', 'systemsettings.exe',
]);

function normalizedAppName(name) {
  return String(name || '').split(/[\\/]/).pop().toLocaleLowerCase('vi');
}

function appPresentation(app) {
  const filename = normalizedAppName(app.name);
  const known = knownAppCatalog[filename];
  const fallback = (app.name.replace(/\.exe$/i, '').match(/[\p{L}\p{N}]/u) || ['?'])[0].toLocaleUpperCase('vi');
  return known || {label: app.name.replace(/\.exe$/i, '') || app.name, icon:fallback, tone:'default'};
}

function isSystemApp(app) {
  const filename = normalizedAppName(app.name);
  if (knownAppCatalog[filename]) return false;
  return systemAppNames.has(filename) || /(?:service|host|broker|helper|updater?|installer|unsecapp|resume)(?:\.exe)?$/i.test(filename);
}

function createAppRow(app) {
  const presentation = appPresentation(app);
  const item = document.createElement('li'); item.className = 'app-row';
  item.dataset.appKind = isSystemApp(app) ? 'system' : 'user';
  const primary = document.createElement('div'); primary.className = 'app-primary';
  const icon = document.createElement('span');
  icon.className = 'app-icon app-icon-' + presentation.tone;
  icon.textContent = presentation.icon; icon.setAttribute('aria-hidden', 'true');
  const identity = document.createElement('div'); identity.className = 'app-identity';
  const nameLine = document.createElement('div'); nameLine.className = 'app-name-line';
  const name = document.createElement('strong'); name.textContent = presentation.label;
  nameLine.append(name);
  if (presentation.label.toLocaleLowerCase('vi') !== app.name.replace(/\.exe$/i, '').toLocaleLowerCase('vi')) {
    const filename = document.createElement('span'); filename.className = 'app-file-name'; filename.textContent = app.name;
    nameLine.append(filename);
  }
  const context = document.createElement('span'); context.className = 'hint';
  context.textContent = app.last_seen
    ? 'Đã thấy ' + new Date(app.last_seen * 1000).toLocaleString('vi-VN', {hour12:false}) +
      (app.devices.size ? ' · ' + [...app.devices].join(', ') : '')
    : 'Quy tắc đã lưu trước đây';
  const details = document.createElement('details'); details.className = 'app-technical';
  const summary = document.createElement('summary'); summary.textContent = 'Chi tiết kỹ thuật';
  const technical = document.createElement('code');
  technical.textContent = 'Tệp: ' + app.name + '\nMã nhận diện: ' + app.sha256;
  details.append(summary, technical); identity.append(nameLine, context, details);
  primary.append(icon, identity);
  const label = document.createElement('label'); label.className = 'app-action';
  const labelText = document.createElement('span'); labelText.textContent = 'Quyền sử dụng';
  const select = document.createElement('select');
  select.setAttribute('aria-label', 'Quyền sử dụng ' + app.name);
  select.append(new Option('Theo quy tắc chung', 'default'), new Option('Cho phép', 'allow'), new Option('Chặn', 'block'));
  select.value = appRuleState(app.sha256);
  select.addEventListener('change', () => setAppRule(app, select.value));
  label.append(labelText, select); item.append(primary, label);
  return item;
}

function renderAppCatalog() {
  const byHash = new Map();
  for (const app of observedApps) {
    const current = byHash.get(app.sha256);
    if (!current) byHash.set(app.sha256, {...app, devices: new Set([app.device_name])});
    else {
      current.devices.add(app.device_name);
      if (app.last_seen > current.last_seen) current.last_seen = app.last_seen;
    }
  }
  for (const key of ['app_allow', 'app_block']) {
    for (const rule of appDrafts[key]) {
      if (!byHash.has(rule.sha256)) byHash.set(rule.sha256, {...rule, last_seen: 0, devices: new Set()});
    }
  }
  const search = el('app-search').value.trim().toLocaleLowerCase('vi');
  const apps = [...byHash.values()]
    .filter(app => {
      const presentation = appPresentation(app);
      return !search || (app.name + ' ' + presentation.label).toLocaleLowerCase('vi').includes(search);
    })
    .sort((a, b) => b.last_seen - a.last_seen || a.name.localeCompare(b.name, 'vi'));
  let primaryApps;
  let systemApps = [];
  if (appCatalogView === 'configured') {
    primaryApps = apps.filter(app => appRuleState(app.sha256) !== 'default');
  } else if (appCatalogView === 'all') {
    primaryApps = apps;
  } else {
    primaryApps = apps.filter(app => appRuleState(app.sha256) !== 'default' || !isSystemApp(app));
    systemApps = apps.filter(app => appRuleState(app.sha256) === 'default' && isSystemApp(app));
  }
  el('app-catalog').replaceChildren(...primaryApps.map(createAppRow));
  el('system-app-catalog').replaceChildren(...systemApps.map(createAppRow));
  el('system-app-count').textContent = String(systemApps.length);
  el('system-apps-section').hidden = appCatalogView !== 'featured' || !systemApps.length;
  if (search && systemApps.length) el('system-apps-section').open = true;
  if (!byHash.size) el('app-catalog-status').textContent = 'Chưa phát hiện ứng dụng. Hãy để con đăng nhập và mở ứng dụng trên thiết bị đã kết nối.';
  else if (!apps.length) el('app-catalog-status').textContent = 'Không tìm thấy ứng dụng phù hợp.';
  else if (appCatalogView === 'configured' && !primaryApps.length) el('app-catalog-status').textContent = 'Chưa có ứng dụng nào được đặt quyền riêng.';
  else {
    const hiddenCount = systemApps.length;
    el('app-catalog-status').textContent = apps.length + ' ứng dụng' + (search ? ' phù hợp' : ' đã phát hiện') +
      (hiddenCount ? ' · ' + hiddenCount + ' tiến trình nền được thu gọn.' : '.');
  }
}

el('app-search').addEventListener('input', renderAppCatalog);
document.querySelectorAll('[data-app-view]').forEach(button => button.addEventListener('click', () => {
  appCatalogView = button.dataset.appView;
  document.querySelectorAll('[data-app-view]').forEach(option => {
    option.setAttribute('aria-pressed', String(option === button));
  });
  renderAppCatalog();
}));
el('filtering-form').elements.enabled.addEventListener('change', updateAppControlWarning);

let domainInspectionSequence = 0;
let categoryCatalog = null;
function clearDomainInspection() {
  domainInspectionSequence++;
  el('inspect-result').textContent = '';
  delete el('inspect-result').dataset.action;
}
async function loadCategoryCatalog() {
  if (!categoryCatalog) categoryCatalog = await api('/filtering/catalog');
  if (!csrf) return;
  renderCategoryCatalog();
}
function renderCategoryCatalog() {
  if (!categoryCatalog) return;
  const container = el('category-groups');
  const search = el('category-search').value.trim().toLowerCase();
  const sections = [];
  for (const group of categoryCatalog.groups) {
    const domains = [...group.domains].sort();
    const visible = domains.filter(domain => domain.includes(search));
    const section = document.createElement('section'); section.className = 'category-domains';
    section.dataset.group = group.key;
    const heading = document.createElement('div'); heading.className = 'category-domains-heading';
    const title = document.createElement('strong');
    title.textContent = 'Danh sách gợi ý – ' + group.label + ' (' + (search ? visible.length + '/' : '') + domains.length + ')';
    const copy = document.createElement('button'); copy.type = 'button'; copy.className = 'secondary category-copy'; copy.textContent = 'Sao chép';
    copy.disabled = !visible.length;
    copy.addEventListener('click', async () => {
      try {
        await copyText(visible.join('\n'));
        copy.textContent = 'Đã sao chép';
        window.setTimeout(() => { copy.textContent = 'Sao chép'; }, 1600);
      } catch (error) { tell('Không thể sao chép danh sách: ' + error.message); }
    });
    heading.append(title, copy);
    const note = document.createElement('p'); note.className = 'hint';
    note.textContent = 'Danh sách gợi ý để tham khảo và thử nhanh; không tham gia quyết định chặn/cho phép.';
    const list = document.createElement('textarea');
    list.className = 'category-suggestion-list'; list.readOnly = true; list.spellcheck = false;
    list.setAttribute('aria-label', 'Website gợi ý thuộc nhóm ' + group.label);
    list.value = visible.join('\n');
    section.append(heading, note, list); sections.push(section);
  }
  container.replaceChildren(...sections);
  el('category-catalog-status').dataset.loaded = 'true';
  el('category-catalog-status').textContent = '';
}
el('category-search').addEventListener('input', renderCategoryCatalog);
el('category-search').addEventListener('keydown', event => { if (event.key === 'Enter') event.preventDefault(); });
async function inspectDomain() {
  clearDomainInspection();
  const sequence = domainInspectionSequence;
  const childId = el('child-select').value;
  try {
    if (!currentFiltering || currentFiltering.child_id !== childId) throw new Error('Hãy chọn hồ sơ của con.');
    syncBulkDomainDrafts();
    if (document.querySelector('.domain-row-edit') || rowDomainLists.some(key => el(key + '-new').value.trim())) throw new Error('Hãy thêm hoặc lưu dòng tên miền đang nhập trước khi kiểm tra.');
    const domain = normalizeDomain(el('inspect-domain').value);
    const data = new FormData(el('filtering-form'));
    const rules = {enabled:data.get('enabled') === 'on', dns_proxy_enabled:data.get('dns_proxy_enabled') === 'on', domain_mode:data.get('domain_mode'),
      category_actions:{...(currentFiltering.category_actions || {})}, category_overrides:{...(currentFiltering.category_overrides || {})}};
    domainLists.forEach(key => { rules[key] = [...domainDrafts[key]]; });
    el('inspect-result').textContent = 'Đang kiểm tra…';
    const result = await api('/children/' + encodeURIComponent(childId) + '/filtering/preview', 'POST', {domain, rules});
    if (!csrf || sequence !== domainInspectionSequence || el('child-select').value !== childId) return;
    el('inspect-result').dataset.action = result.action;
    el('inspect-result').textContent = result.domain + '\n' +
      (result.action === 'block' ? 'CHẶN' : 'CHO PHÉP') + ' — ' + result.reason;
  } catch (error) {
    if (sequence === domainInspectionSequence) el('inspect-result').textContent = error.message;
  }
}
el('inspect-domain-button').addEventListener('click', inspectDomain);
el('child-select').addEventListener('change', clearDomainInspection);
el('logout').addEventListener('click', clearDomainInspection);
el('inspect-domain').addEventListener('input', clearDomainInspection);
el('inspect-domain').addEventListener('keydown', event => {
  if (event.key === 'Enter') { event.preventDefault(); inspectDomain(); }
});

form('filtering-form', async data => {
  if (!currentFiltering) throw new Error('Hãy chọn hồ sơ của con.');
  syncBulkDomainDrafts();
  if (document.querySelector('.domain-row-edit')) throw new Error('Hãy lưu hoặc hủy dòng tên miền đang chỉnh sửa trước.');
  if (rowDomainLists.some(key => el(key + '-new').value.trim())) throw new Error('Hãy bấm Thêm để đưa tên miền vừa nhập vào danh sách trước khi lưu.');
  const childId = currentFiltering.child_id;
  const body = {expected_version: currentFiltering.version, enabled: data.get('enabled') === 'on',
    dns_proxy_enabled: data.get('dns_proxy_enabled') === 'on',
    domain_mode: data.get('domain_mode'), app_mode: data.get('app_mode')};
  body.safe_search = data.get('safe_search') === 'on';
  body.category_overrides = {...(currentFiltering.category_overrides || {})};
  body.category_actions = {...(currentFiltering.category_actions || {})};
  domainLists.forEach(key => { body[key] = [...domainDrafts[key]]; });
  ['app_allow', 'app_block'].forEach(key => { body[key] = appDrafts[key].map(rule => ({...rule})); });
  await api('/children/' + encodeURIComponent(childId) + '/filtering', 'PUT', body);
  await loadFiltering(childId, true);
  tell('Đã lưu quy tắc. Máy của con sẽ nhận khi kết nối với máy chủ.');
});

async function refreshActivity() {
  const childId = el('child-select').value;
  const sequence = ++activitySequence;
  if (!childId) { el('activity-rows').replaceChildren(); el('activity-empty').textContent = 'Chưa có hồ sơ.'; return; }
  const [result, deletion] = await Promise.all([
    api('/children/' + encodeURIComponent(childId) + '/activity-events?offset=' + activityOffset),
    api('/children/' + encodeURIComponent(childId) + '/activity-data/deletion')
  ]);
  if (!csrf || sequence !== activitySequence || childId !== el('child-select').value) return;
  el('activity-rows').replaceChildren(...result.items.map(item => {
    const row = document.createElement('tr');
    [new Date(item.event.ts * 1000).toLocaleString('vi-VN', {hour12: false}), item.event.subject,
      item.explanation.reason + ' · ' + item.explanation.rule_author].forEach(value => {
      const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
    });
    return row;
  }));
  el('activity-empty').textContent = result.items.length ? '' : 'Chưa có sự kiện chặn trong trang này.';
  el('activity-prev').disabled = activityOffset === 0;
  el('activity-next').disabled = !result.has_more;
  el('activity-page').textContent = 'Trang ' + (activityOffset / 50 + 1);
  el('deletion-status').textContent = !deletion.generation ? '' : deletion.complete ?
    'Dữ liệu cũ đã được xóa trên máy chủ và các agent đã xác nhận xóa bộ đệm.' :
    'Đã xóa trên máy chủ. Đang chờ agent xóa bộ đệm: ' + deletion.pending_devices.map(device => device.name + (device.revoked ? ' (đã thu hồi, cần xóa dữ liệu trên máy)' : '')).join(', ') + '. Thiết bị ngoại tuyến còn được ghép đôi sẽ xóa khi kết nối lại.';
}
function selectDashboardTab(name) {
  activeDashboardTab = name;
  dashboardTabs.forEach(tab => {
    const selected = tab === name;
    el(tab + '-panel').hidden = !selected;
    el(tab + '-tab').setAttribute('aria-selected', String(selected));
    el(tab + '-tab').tabIndex = selected ? 0 : -1;
  });
  if (csrf) refreshSelectedChildTab().catch(error => tell(error.message));
}
dashboardTabs.forEach((name, index) => {
  const tab = el(name + '-tab');
  tab.addEventListener('click', () => selectDashboardTab(name));
  tab.addEventListener('keydown', event => {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % dashboardTabs.length;
    else if (event.key === 'ArrowLeft') next = (index + dashboardTabs.length - 1) % dashboardTabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = dashboardTabs.length - 1;
    else return;
    event.preventDefault();
    selectDashboardTab(dashboardTabs[next]);
    el(dashboardTabs[next] + '-tab').focus();
  });
});
el('activity-prev').addEventListener('click', () => { activityOffset = Math.max(0, activityOffset - 50); refreshActivity().catch(error => tell(error.message)); });
el('activity-next').addEventListener('click', () => { activityOffset += 50; refreshActivity().catch(error => tell(error.message)); });
el('erase-activity').addEventListener('click', async () => {
  const childId = el('child-select').value;
  if (!childId || !window.confirm('Xóa toàn bộ lịch sử sự kiện hoạt động của hồ sơ này trên máy chủ và các máy của con? Thao tác này không thể hoàn tác.')) return;
  const button = el('erase-activity'); button.disabled = true;
  try {
    await api('/children/' + encodeURIComponent(childId) + '/activity-data', 'DELETE');
    activityOffset = 0;
    await refreshActivity();
    await refreshReport();
  } catch (error) { tell(error.message); } finally { button.disabled = false; }
});

function normalizeDomain(value) {
  value = value.trim();
  if (!value || /\s/.test(value)) throw new Error('Nhập một tên miền hoặc URL hợp lệ.');
  const url = new URL(value.includes('://') ? value : 'https://' + value);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error('Chỉ nhập tên miền hoặc URL http/https không có thông tin đăng nhập.');
  const domain = url.hostname.toLowerCase().replace(/\.$/, '');
  if (domain.length > 253 || !domain.includes('.') || /^\d+(\.\d+){3}$/.test(domain) || domain.split('.').some(label => !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label))) throw new Error('Nhập tên miền hợp lệ, ví dụ example.org.');
  return domain;
}
async function copyText(value) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(value);
  const fallback = document.createElement('textarea'); fallback.value = value; fallback.setAttribute('readonly', '');
  fallback.style.position = 'fixed'; fallback.style.opacity = '0'; document.body.append(fallback); fallback.select();
  const copied = document.execCommand('copy'); fallback.remove();
  if (!copied) throw new Error('trình duyệt không cấp quyền truy cập clipboard');
}
function parseBulkDomainList(key, report = true) {
  const editor = el(key + '-editor');
  const lines = editor.value.split(/\r?\n/); const domains = []; const seen = new Set();
  try {
    lines.forEach((line, index) => {
      if (!line.trim()) return;
      let domain;
      try { domain = normalizeDomain(line); }
      catch (error) { throw new Error('Dòng ' + (index + 1) + ': ' + error.message); }
      if (!seen.has(domain)) { seen.add(domain); domains.push(domain); }
    });
    if (domains.length > 500) throw new Error('Mỗi danh sách hỗ trợ tối đa 500 tên miền.');
    if (report) { el(key + '-status').dataset.error = ''; el(key + '-status').textContent = domains.length + ' website trong danh sách.'; }
    return domains;
  } catch (error) {
    if (report) { el(key + '-status').dataset.error = 'true'; el(key + '-status').textContent = error.message; }
    throw error;
  }
}
function syncBulkDomainDrafts() {
  bulkDomainLists.forEach(key => { domainDrafts[key] = parseBulkDomainList(key); });
}
const domainSearchPositions = {domain_block: -1, domain_allow: -1, safety_domains: -1};
function findNextDomain(key) {
  const editor = el(key + '-editor'); const query = el(key + '-search').value.trim().toLowerCase();
  if (!query) { el(key + '-status').textContent = 'Nhập nội dung cần tìm.'; return; }
  const lines = editor.value.split(/\r?\n/); const matches = [];
  let offset = 0;
  lines.forEach((line, index) => { if (line.toLowerCase().includes(query)) matches.push({index, start: offset, end: offset + line.length}); offset += line.length + 1; });
  if (!matches.length) { domainSearchPositions[key] = -1; el(key + '-status').textContent = 'Không tìm thấy website phù hợp.'; return; }
  domainSearchPositions[key] = (domainSearchPositions[key] + 1) % matches.length;
  const match = matches[domainSearchPositions[key]]; editor.focus(); editor.setSelectionRange(match.start, match.end);
  el(key + '-status').dataset.error = ''; el(key + '-status').textContent = 'Kết quả ' + (domainSearchPositions[key] + 1) + '/' + matches.length + ' · dòng ' + (match.index + 1) + '.';
}
function markFilteringDirty() {
  clearDomainInspection();
  filteringDirty = true;
  el('filtering-draft-status').textContent = 'Có thay đổi chưa lưu. Bấm Lưu quy tắc kiểm soát để áp dụng.';
}
function domainInputValue(input, key, ignoredIndex = -1) {
  input.setCustomValidity('');
  try {
    const domain = normalizeDomain(input.value);
    if (domainDrafts[key].some((item, index) => index !== ignoredIndex && item === domain)) throw new Error('Tên miền này đã có trong danh sách.');
    return domain;
  } catch (error) {
    input.setCustomValidity(error.message);
    input.reportValidity();
    return null;
  }
}
function renderDomainLists() {
  bulkDomainLists.forEach(key => {
    el(key + '-editor').value = domainDrafts[key].join('\n');
    el(key + '-status').dataset.error = '';
    el(key + '-status').textContent = domainDrafts[key].length + ' website trong danh sách.';
  });
  rowDomainLists.forEach(key => {
    const list = el(key + '-list');
    const rows = domainDrafts[key].map((domain, index) => {
      const row = document.createElement('li'); row.className = 'domain-row';
      const name = document.createElement('span'); name.className = 'domain-name'; name.textContent = domain;
      row.append(name);
      const actions = document.createElement('div'); actions.className = 'domain-row-actions'; row.append(actions);
      if (key === 'safety_domains' && domain === mandatorySafetyDomain) {
        const note = document.createElement('span'); note.className = 'hint'; note.textContent = 'Luôn được phép'; actions.append(note); return row;
      }
      const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'secondary'; edit.textContent = 'Chỉnh sửa'; edit.setAttribute('aria-label', 'Chỉnh sửa ' + domain);
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'domain-delete'; remove.textContent = 'Xóa'; remove.setAttribute('aria-label', 'Xóa ' + domain);
      remove.addEventListener('click', () => {
        if (document.querySelector('.domain-row-edit')) { tell('Hãy lưu hoặc hủy dòng đang chỉnh sửa trước.'); return; }
        domainDrafts[key].splice(index, 1); markFilteringDirty(); renderDomainLists();
      });
      edit.addEventListener('click', () => {
        if (document.querySelector('.domain-row-edit')) { tell('Hãy lưu hoặc hủy dòng đang chỉnh sửa trước.'); return; }
        markFilteringDirty();
        const input = document.createElement('input'); input.value = domain; input.maxLength = 2048; input.setAttribute('aria-label', 'Tên miền thay thế cho ' + domain);
        input.addEventListener('input', () => input.setCustomValidity(''));
        row.classList.add('domain-row-edit'); row.replaceChildren(input, actions); actions.replaceChildren();
        const save = document.createElement('button'); save.type = 'button'; save.textContent = 'Lưu dòng';
        const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'secondary'; cancel.textContent = 'Hủy';
        const commit = () => { const value = domainInputValue(input, key, index); if (!value) return; domainDrafts[key][index] = value; markFilteringDirty(); renderDomainLists(); };
        save.addEventListener('click', commit); cancel.addEventListener('click', renderDomainLists);
        input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); commit(); } else if (event.key === 'Escape') { event.preventDefault(); renderDomainLists(); } });
        actions.append(save, cancel); input.focus(); input.select();
      });
      actions.append(edit, remove); return row;
    });
    if (!rows.length) { const empty = document.createElement('li'); empty.className = 'domain-empty'; empty.textContent = 'Chưa có tên miền trong danh sách này.'; rows.push(empty); }
    list.replaceChildren(...rows);
  });
  el('filtering-draft-status').textContent = filteringDirty ? 'Có thay đổi chưa lưu. Bấm Lưu quy tắc kiểm soát để áp dụng.' : '';
}
function addDomain(key) {
  if (document.querySelector('.domain-row-edit')) { tell('Hãy lưu hoặc hủy dòng đang chỉnh sửa trước.'); return; }
  const input = el(key + '-new');
  const value = domainInputValue(input, key);
  if (!value) return;
  domainDrafts[key].push(value); input.value = ''; markFilteringDirty(); renderDomainLists(); input.focus();
}
rowDomainLists.forEach(key => {
  document.querySelector('[data-add-domain="' + key + '"]').addEventListener('click', () => addDomain(key));
  el(key + '-new').addEventListener('input', () => el(key + '-new').setCustomValidity(''));
  el(key + '-new').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); addDomain(key); } });
});
bulkDomainLists.forEach(key => {
  el(key + '-editor').addEventListener('input', () => {
    domainSearchPositions[key] = -1;
    try { domainDrafts[key] = parseBulkDomainList(key); } catch (_) { /* Hiển thị lỗi tại hộp hiện tại. */ }
  });
  el(key + '-search').addEventListener('input', () => { domainSearchPositions[key] = -1; });
  el(key + '-search').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); findNextDomain(key); } });
  document.querySelector('[data-find-domain="' + key + '"]').addEventListener('click', () => findNextDomain(key));
});
el('filtering-form').addEventListener('input', event => {
  if (!['inspect-domain','category-search','app-search','domain_block-search','domain_allow-search','safety_domains-search'].includes(event.target.id) && event.target.matches('input, select, textarea')) markFilteringDirty();
});
el('reload-filtering').addEventListener('click', () => {
  if (filteringDirty && !window.confirm('Tải lại sẽ bỏ các thay đổi quy tắc chưa lưu. Tiếp tục?')) return;
  const childId = el('child-select').value;
  if (childId) loadFiltering(childId, true).catch(error => tell(error.message));
});
renderDomainLists();

function clearReport() {
  reportCache = {key: '', loadedAt: 0};
  appReportCache = {key: '', loadedAt: 0};
  ['report-daily', 'report-weekly', 'report-apps', 'report-domains', 'report-requests', 'report-duration', 'report-blocked'].forEach(id => el(id).replaceChildren());
  ['report-domains', 'report-requests'].forEach(id => { delete el(id).dataset.signature; });
  el('report-daily-total').textContent = '—';
  el('report-weekly-total').textContent = '—';
  el('report-status').textContent = '';
}
function rollingWeeksFromDaily(daily) {
  if (daily.length !== 56) throw new Error('Chưa đủ dữ liệu 8 tuần để vẽ biểu đồ.');
  const weeks = [];
  for (let index = 0; index < 56; index += 7) {
    const group = daily.slice(index, index + 7);
    weeks.push({week_start: group[0].date, week_end: group[6].date,
      duration_sec: group.reduce((total, day) => total + day.duration_sec, 0)});
  }
  return weeks;
}
function chartDateLabel(value, includeWeekday = false) {
  const date = new Date(value + 'T00:00:00Z');
  const dayMonth = String(date.getUTCDate()).padStart(2, '0') + '/' + String(date.getUTCMonth() + 1).padStart(2, '0');
  if (!includeWeekday) return dayMonth;
  return ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'][date.getUTCDay()] + '\n' + dayMonth;
}
function chartScaleLabel(seconds) {
  if (seconds < 60) return seconds + ' giây';
  if (seconds < 3600) return Math.ceil(seconds / 60) + ' phút';
  const hours = seconds / 3600;
  return (hours >= 10 ? Math.round(hours) : Math.round(hours * 10) / 10) + ' giờ';
}
function renderReportColumns(id, childId, kind, items) {
  const signature = childId + ':' + kind + ':' + JSON.stringify(items);
  if (el(id).firstElementChild?.dataset.signature === signature) return;
  const wrap = document.createElement('div'); wrap.className = 'report-bars-chart';
  wrap.dataset.signature = signature;
  const maximum = Math.max(1, ...items.map(item => item.duration_sec));
  const scale = document.createElement('div'); scale.className = 'report-chart-scale';
  [maximum, maximum / 2, 0].forEach(value => {
    const tick = document.createElement('span'); tick.textContent = chartScaleLabel(Math.round(value)); scale.append(tick);
  });
  const plot = document.createElement('div'); plot.className = 'report-chart-plot';
  plot.style.gridTemplateColumns = 'repeat(' + items.length + ', minmax(0, 1fr))';
  items.forEach((item, index) => {
    const column = document.createElement('div'); column.className = 'report-bar-column';
    const hit = document.createElement('button'); hit.type = 'button'; hit.className = 'report-column-hit';
    const label = (kind === 'daily' ? 'Ngày ' + item.date : 'Tuần ' + item.week_start + ' – ' + item.week_end) + ': ' + formatDuration(item.duration_sec);
    hit.title = label; hit.setAttribute('aria-label', label);
    hit.style.setProperty('--bar-height', (item.duration_sec ? Math.max(4, item.duration_sec / maximum * 100) : 2) + '%');
    const value = document.createElement('span'); value.className = 'report-bar-value';
    value.textContent = item.duration_sec ? chartScaleLabel(item.duration_sec) : '';
    const date = document.createElement('span'); date.className = 'report-bar-label';
    date.textContent = kind === 'daily' ? chartDateLabel(item.date, true) : chartDateLabel(item.week_start);
    column.append(value, hit, date); plot.append(column);
  });
  wrap.append(scale, plot);
  el(id).replaceChildren(wrap);
}
function renderAppChart(childId, days, items) {
  const signature = childId + ':' + days + ':' + JSON.stringify(items);
  if (el('report-apps').firstElementChild?.dataset.signature === signature) return;
  const list = document.createElement('ol'); list.className = 'report-app-bars';
  list.dataset.signature = signature;
  const maximum = Math.max(1, ...items.map(item => item.duration_sec));
  items.forEach(item => {
    const line = document.createElement('li');
    const heading = document.createElement('div'); heading.className = 'report-app-heading';
    const name = document.createElement('strong'); name.textContent = item.subject;
    const duration = document.createElement('span'); duration.textContent = formatDuration(item.duration_sec);
    const track = document.createElement('div'); track.className = 'report-app-track';
    const bar = document.createElement('span'); bar.style.width = (item.duration_sec / maximum * 100) + '%';
    track.append(bar); heading.append(name, duration); line.append(heading, track);
    list.append(line);
  });
  if (!items.length) {
    const empty = document.createElement('li'); empty.className = 'report-app-empty';
    empty.textContent = 'Chưa có dữ liệu ứng dụng trong khoảng này.'; list.append(empty);
  }
  el('report-apps').replaceChildren(list);
}
function renderReportList(id, lines, empty) {
  const signature = JSON.stringify(lines);
  if (el(id).dataset.signature === signature) return;
  renderList(id, lines, empty);
  el(id).dataset.signature = signature;
}
function setReportText(id, value) {
  if (el(id).textContent !== value) el(id).textContent = value;
}
async function refreshAppChart() {
  const childId = el('child-select').value;
  if (!childId) return;
  const days = el('report-app-period').value;
  const key = childId + ':' + days;
  if (appReportCache.key === key && Date.now() - appReportCache.loadedAt < REPORT_REFRESH_MS) return;
  const sequence = ++appReportSequence;
  appReportCache = {key, loadedAt: Date.now()};
  try {
    const result = await api('/children/' + encodeURIComponent(childId) + '/activity-report?days=' + days);
    if (!csrf || sequence !== appReportSequence || el('child-select').value !== childId || el('report-app-period').value !== days) return;
    renderAppChart(childId, days, result.top_apps);
  } catch (error) {
    if (appReportCache.key === key) appReportCache = {key: '', loadedAt: 0};
    throw error;
  }
}
async function refreshReport() {
  const childId = el('child-select').value;
  if (!childId) { clearReport(); el('report-status').textContent = 'Hãy chọn hồ sơ của con để xem hoạt động.'; return; }
  const days = el('report-days').value;
  const key = childId + ':' + days;
  if (reportCache.key === key && Date.now() - reportCache.loadedAt < REPORT_REFRESH_MS) return;
  const sequence = ++reportSequence;
  reportCache = {key, loadedAt: Date.now()};
  let result, chartReport;
  try {
    [result, chartReport] = await Promise.all([
      api('/children/' + encodeURIComponent(childId) + '/activity-report?days=' + days),
      api('/children/' + encodeURIComponent(childId) + '/activity-report?days=56'),
    ]);
  } catch (error) {
    if (reportCache.key === key) reportCache = {key: '', loadedAt: 0};
    throw error;
  }
  if (!csrf || sequence !== reportSequence || el('child-select').value !== childId || el('report-days').value !== days) return;
  setReportText('report-status', result.start_date + ' → ' + result.end_date + ' · giờ Việt Nam');
  setReportText('report-duration', 'Dùng máy: ' + formatDuration(result.total_duration_sec));
  setReportText('report-blocked', 'Bị chặn: ' + result.blocked_count + ' lần');
  const daily = chartReport.daily.slice(-7);
  const weekly = rollingWeeksFromDaily(chartReport.daily);
  setReportText('report-daily-total', formatChartDuration(daily.reduce((total, day) => total + day.duration_sec, 0)));
  setReportText('report-weekly-total', formatChartDuration(weekly.reduce((total, week) => total + week.duration_sec, 0)));
  renderReportColumns('report-daily', childId, 'daily', daily);
  renderReportColumns('report-weekly', childId, 'weekly', weekly);
  await refreshAppChart();
  renderReportList('report-domains', result.top_domains.map(item => item.subject + ': ' + item.queries + ' lượt truy vấn'), 'Chưa có truy vấn tên miền.');
  const statuses = {pending:'Đang chờ', approved:'Được đồng ý', rejected:'Chưa được đồng ý'};
  renderReportList('report-requests', result.requests.map(item => new Date(item.created_at * 1000).toLocaleString('vi-VN', {timeZone:'Asia/Ho_Chi_Minh'}) + ': xin ' + item.minutes + ' phút · ' + (statuses[item.status] || item.status)), 'Chưa có yêu cầu trong khoảng này.');
}
el('report-days').addEventListener('change', () => refreshReport().catch(error => { el('report-status').textContent = error.message; }));
el('report-app-period').addEventListener('change', () => refreshAppChart().catch(error => { el('report-status').textContent = error.message; }));
el('export-week').addEventListener('click', async () => {
  const childId = el('child-select').value;
  if (!childId) { tell('Hãy chọn hồ sơ của con.'); return; }
  const button = el('export-week'); button.disabled = true;
  try {
    const response = await fetch('/api/children/' + encodeURIComponent(childId) + '/activity-report.pdf', {credentials:'same-origin'});
    if (!response.ok) { if (response.status === 401) showLogin(); throw new Error('Chưa thể xuất báo cáo. Hãy thử lại.'); }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a'); link.href = url; link.download = 'bao-cao-tuan.pdf'; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    tell('Đã tải báo cáo tuần. Tệp tải về nằm ngoài phạm vi tự xóa 90 ngày của hệ thống.');
  } catch (error) { tell(error.message); } finally { button.disabled = false; }
});
