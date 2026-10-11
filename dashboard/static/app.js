"use strict";
let csrf = "";
let currentPolicy = null;
let currentFiltering = null;
let filteringDirty = false;
let filteringSequence = 0;
let reportSequence = 0;
let appReportSequence = 0;
const REPORT_REFRESH_MS = 60 * 1000;
let reportCache = {key: '', loadedAt: 0};
let appReportCache = {key: '', loadedAt: 0};
const domainLists = ['domain_block', 'domain_allow', 'safety_domains'];
let domainDrafts = {domain_block: [], domain_allow: [], safety_domains: []};
const dashboardTabs = ['overview', 'report', 'time-policy', 'filtering', 'activity'];
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
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/login") showLogin();
    throw new Error(typeof data.detail === "string" ? data.detail : "Dữ liệu chưa hợp lệ.");
  }
  return data;
}
function showLogin() {
  if (liveEvents) { liveEvents.close(); liveEvents = null; }
  if (liveRefreshTimer) { clearTimeout(liveRefreshTimer); liveRefreshTimer = null; }
  pendingLiveKinds.clear();
  csrf = ""; currentPolicy = null; childProfiles = [];
  currentFiltering = null; activityOffset = 0; activitySequence++;
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
  el("pairing-code").textContent = "";
  el("code-form").reset();
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
  await loadFiltering(id);
}
async function loadChildren(preferredId = null) {
  const rows = await api("/children");
  childProfiles = rows;
  const oldId = preferredId || el("child-select").value;
  el("child-select").replaceChildren(...rows.map(row => new Option(row.display_name, row.id)));
  if (rows.some(row => row.id === oldId)) el("child-select").value = oldId;
  const selected = rows.find(row => row.id === el("child-select").value);
  if (el('child-select').value !== oldId) activityOffset = 0;
  el("child-pin-status").textContent = selected ? (selected.has_pin ? "PIN đã được thiết lập." : "Hồ sơ cũ chưa có PIN; hãy tạo PIN trước khi đăng nhập trên máy trẻ.") : "";
  await loadPolicy();
  await refreshReport();
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
  const labels = {enabled:'Kiểm soát', weekday_minutes:'Ngày thường', weekend_minutes:'Cuối tuần', domain_mode:'Quy tắc web', app_mode:'Quy tắc ứng dụng'};
  const value = (key, item) => key === 'enabled' ? (item ? 'bật' : 'tắt') : key.endsWith('_minutes') ? item + ' phút' : key.endsWith('_mode') ? ({blocklist:'chặn theo danh sách',allowlist:'chỉ cho phép danh sách'}[item] || item) : String(item);
  for (const key of Object.keys(labels)) {
    if (key in next && old[key] !== next[key]) changes.push(labels[key] + ': ' + (key in old ? value(key, old[key]) + ' → ' : '') + value(key, next[key]));
  }
  for (const [key, label] of Object.entries({domain_block:'web bị chặn', domain_allow:'web được phép', safety_domains:'web an toàn', app_block:'ứng dụng bị chặn', app_allow:'ứng dụng được phép'})) {
    const describe = item => typeof item === 'string' ? item : item.name + ' (SHA-256 ' + item.sha256 + ')';
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
  const action = ({policy_updated:'Chính sách thời gian',filtering_updated:'Kiểm soát web và ứng dụng',enrollment_consent:'Ghép thiết bị',emergency_command_created:'Lệnh thiết bị',emergency_command_acknowledged:'Thiết bị xác nhận lệnh',time_requested:'Yêu cầu thêm giờ',time_request_decided:'Trả lời yêu cầu thêm giờ',child_pin_changed:'PIN hồ sơ'}[a.action] || a.action);
  const child = childProfiles.find(item => item.id === a.child_id);
  return new Date(a.ts * 1000).toLocaleString('vi-VN') + ' · ' + action + (child ? ' · ' + child.display_name : '') + (a.actor ? ' · ' + a.actor : '') + (changes.length ? ': ' + changes.join('; ') : '');
}
async function refreshStatus() {
  await refreshActivity();
  await refreshReport().catch(error => { el('report-status').textContent = error.message; });
  const [devices, audits, requests] = await Promise.all([
    api("/devices"), api("/audit"), api("/time-requests")
  ]);
  const deviceItems = devices.length ? devices.map(d => {
    const li = document.createElement("li");
    const state = !d.online ? "offline" : d.active_user ? "active" : "online";
    li.className = "device-card device-card--" + state;
    const title = document.createElement("h3"); title.textContent = d.display_name;
    const details = document.createElement("div"); details.className = "device-details";
    const detail = (label, value) => {
      const line = document.createElement("div"); line.className = "device-detail";
      const name = document.createElement("strong"); name.textContent = label + ": ";
      const content = document.createElement("span"); content.textContent = value;
      line.append(name, content); details.append(line); return content;
    };
    detail("Trạng thái", d.online ? "Trực tuyến" : "Ngoại tuyến");
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
      button.addEventListener("click", () => sendCommand(d.id, command, button)); actions.append(button);
    });
    const minutes = document.createElement("input"); minutes.type = "number"; minutes.min = "1";
    minutes.max = "120"; minutes.value = deviceGrantMinutes.get(d.id) || "15"; minutes.className = "grant-minutes";
    minutes.setAttribute("aria-label", "Số phút cộng thêm hôm nay");
    minutes.addEventListener("input", () => deviceGrantMinutes.set(d.id, minutes.value));
    const grant = document.createElement("button"); grant.type = "button"; grant.textContent = "Cộng phút";
    grant.disabled = !d.active_child_id;
    grant.addEventListener("click", () => sendCommand(d.id, "add_time", grant, Number(minutes.value)));
    actions.append(minutes, grant);
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
      else if (kinds.has("policy")) await loadPolicy();
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
  el("login-panel").hidden = true; el("workspace").hidden = false;
  await loadChildren(); await refreshStatus();
  connectLiveUpdates();
}
function form(id, handler) {
  el(id).addEventListener("submit", async (event) => {
    event.preventDefault(); tell("");
    const button = event.submitter || event.target.querySelector('button[type="submit"]') || event.target.querySelector("button");
    button.disabled = true;
    try { await handler(new FormData(event.target)); }
    catch (error) { tell(error.message); }
    finally { button.disabled = false; }
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
  activityOffset = 0;
  activitySequence++;
  el('activity-rows').replaceChildren();
  const selected = childProfiles.find(row => row.id === el("child-select").value);
  el("child-pin-status").textContent = selected ? (selected.has_pin ? "PIN đã được thiết lập." : "Hồ sơ cũ chưa có PIN; hãy tạo PIN trước khi đăng nhập trên máy trẻ.") : "";
  loadPolicy().catch(e => tell(e.message));
  refreshActivity().catch(e => tell(e.message));
  refreshReport().catch(e => tell(e.message));
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
  const policy = await api('/children/' + encodeURIComponent(childId) + '/filtering');
  if (!csrf || sequence !== filteringSequence || el('child-select').value !== childId) return;
  if (!force && filteringDirty && currentFiltering?.child_id === childId) return;
  currentFiltering = policy;
  filteringDirty = false;
  const fields = el('filtering-form').elements;
  fields.enabled.checked = policy.enabled;
  ['domain_mode', 'app_mode'].forEach(key => { fields[key].value = policy[key]; });
  domainLists.forEach(key => { domainDrafts[key] = [...policy[key]]; el(key + '-new').value = ''; });
  renderDomainLists();
  ['app_allow', 'app_block'].forEach(key => { fields[key].value = policy[key].map(rule => rule.name + ' | ' + rule.sha256).join('\n'); });
}

function lines(value) { return value.split(/\r?\n/).map(line => line.trim()).filter(Boolean); }
function appRules(value) {
  return lines(value).map(line => {
    const parts = line.split('|').map(part => part.trim());
    if (parts.length !== 2 || !parts[0] || !/^[a-f0-9]{64}$/i.test(parts[1])) throw new Error('Mỗi ứng dụng cần tên tệp và mã SHA-256 gồm 64 ký tự, ngăn cách bằng |.');
    return {name: parts[0], sha256: parts[1].toLowerCase()};
  });
}
form('filtering-form', async data => {
  if (!currentFiltering) throw new Error('Hãy chọn hồ sơ của con.');
  if (document.querySelector('.domain-row-edit')) throw new Error('Hãy lưu hoặc hủy dòng tên miền đang chỉnh sửa trước.');
  if (domainLists.some(key => el(key + '-new').value.trim())) throw new Error('Hãy bấm Thêm để đưa tên miền vừa nhập vào danh sách trước khi lưu.');
  const childId = currentFiltering.child_id;
  const body = {expected_version: currentFiltering.version, enabled: data.get('enabled') === 'on',
    domain_mode: data.get('domain_mode'), app_mode: data.get('app_mode')};
  domainLists.forEach(key => { body[key] = [...domainDrafts[key]]; });
  ['app_allow', 'app_block'].forEach(key => { body[key] = appRules(data.get(key)); });
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
  dashboardTabs.forEach(tab => {
    const selected = tab === name;
    el(tab + '-panel').hidden = !selected;
    el(tab + '-tab').setAttribute('aria-selected', String(selected));
    el(tab + '-tab').tabIndex = selected ? 0 : -1;
  });
  if (name === 'activity' && csrf) refreshActivity().catch(error => tell(error.message));
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
function markFilteringDirty() {
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
  domainLists.forEach(key => {
    const list = el(key + '-list');
    const rows = domainDrafts[key].map((domain, index) => {
      const row = document.createElement('li'); row.className = 'domain-row';
      const name = document.createElement('span'); name.className = 'domain-name'; name.textContent = domain;
      row.append(name);
      const actions = document.createElement('div'); actions.className = 'domain-row-actions'; row.append(actions);
      if (key === 'safety_domains' && domain === '111.vn') {
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
domainLists.forEach(key => {
  document.querySelector('[data-add-domain="' + key + '"]').addEventListener('click', () => addDomain(key));
  el(key + '-new').addEventListener('input', () => el(key + '-new').setCustomValidity(''));
  el(key + '-new').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); addDomain(key); } });
});
el('filtering-form').addEventListener('input', event => {
  if (event.target.matches('input, select, textarea')) markFilteringDirty();
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
function renderReportColumns(id, childId, kind, items) {
  const days = kind === 'daily' ? 7 : 56;
  const signature = childId + ':' + kind + ':' + JSON.stringify(items);
  if (el(id).firstElementChild?.dataset.signature === signature) return;
  const wrap = document.createElement('div'); wrap.className = 'report-chart-image';
  wrap.dataset.signature = signature;
  const image = document.createElement('img');
  image.alt = 'Biểu đồ thời lượng theo ' + (kind === 'daily' ? 'ngày' : 'tuần');
  image.src = '/api/children/' + encodeURIComponent(childId) + '/activity-report/chart.png?kind=' + kind + '&days=' + days + '&t=' + Date.now();
  wrap.append(image);
  items.forEach((item, index) => {
    const hit = document.createElement('button'); hit.type = 'button'; hit.className = 'report-column-hit';
    const label = (kind === 'daily' ? 'Ngày ' + item.date : 'Tuần ' + item.week_start + ' – ' + item.week_end) + ': ' + formatDuration(item.duration_sec);
    hit.title = label; hit.setAttribute('aria-label', label);
    hit.style.left = (9 + index * 88.5 / items.length) + '%';
    hit.style.width = (88.5 / items.length) + '%';
    wrap.append(hit);
  });
  el(id).replaceChildren(wrap);
}
function renderAppChart(childId, days, items) {
  const signature = childId + ':' + days + ':' + JSON.stringify(items);
  if (el('report-apps').firstElementChild?.dataset.signature === signature) return;
  const image = document.createElement('img'); image.alt = 'Biểu đồ top 10 ứng dụng';
  image.dataset.signature = signature;
  image.src = '/api/children/' + encodeURIComponent(childId) + '/activity-report/chart.png?kind=apps&days=' + days + '&t=' + Date.now();
  const list = document.createElement('ol'); list.className = 'sr-only';
  items.forEach(item => {
    const line = document.createElement('li');
    line.textContent = item.subject + ': ' + formatDuration(item.duration_sec);
    list.append(line);
  });
  el('report-apps').replaceChildren(image, list);
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
