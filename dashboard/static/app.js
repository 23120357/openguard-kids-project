"use strict";
let csrf = "";
let currentPolicy = null;
let childProfiles = [];
let liveEvents = null;
let liveRefreshTimer = null;
const pendingLiveKinds = new Set();
const deviceGrantMinutes = new Map();
const el = (id) => document.getElementById(id);
const tell = (message) => { el("message").textContent = message; };
const dayNames = ["Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy", "Chủ nhật"];
const formatDuration = seconds => Math.floor(seconds / 60) + " phút " + String(seconds % 60).padStart(2, "0") + " giây";

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
  el("workspace").hidden = true; el("login-panel").hidden = false;
  ["devices", "audit", "child-select", "pairing-code", "identity"].forEach(id => el(id).replaceChildren());
  el("policy-form").reset(); el("code-form").reset();
}
async function loadPolicy() {
  currentPolicy = null;
  el("pairing-code").textContent = "";
  el("code-form").reset();
  const id = el("child-select").value;
  if (!id) return;
  const policy = await api("/children/" + encodeURIComponent(id) + "/policy");
  if (el("child-select").value !== id) return;
  currentPolicy = policy;
  el("policy-form").elements.enabled.checked = policy.enabled;
  el("policy-form").elements.weekday_minutes.value = policy.weekday_minutes;
  el("policy-form").elements.weekend_minutes.value = policy.weekend_minutes;
  el("policy-version").textContent = "Phiên bản " + policy.version;
  showSchedule(policy.schedule);
}
async function loadChildren(preferredId = null) {
  const rows = await api("/children");
  childProfiles = rows;
  const oldId = preferredId || el("child-select").value;
  el("child-select").replaceChildren(...rows.map(row => new Option(row.display_name, row.id)));
  if (rows.some(row => row.id === oldId)) el("child-select").value = oldId;
  const selected = rows.find(row => row.id === el("child-select").value);
  el("child-pin-status").textContent = selected ? (selected.has_pin ? "PIN đã được thiết lập." : "Hồ sơ cũ chưa có PIN; hãy tạo PIN trước khi đăng nhập trên máy trẻ.") : "";
  await loadPolicy();
}
function renderList(id, lines, empty) {
  el(id).replaceChildren(...(lines.length ? lines : [empty]).map(line => {
    const li = document.createElement("li"); li.textContent = line; return li;
  }));
}
async function refreshStatus() {
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
  renderList("audit", audits.slice(0, 10).map(a =>
    new Date(a.ts * 1000).toLocaleString("vi-VN") + " · " +
    ({policy_updated: "Đã cập nhật chính sách", enrollment_consent: "Đã đồng ý ghép thiết bị",
      emergency_command_created: "Đã gửi lệnh khẩn", emergency_command_acknowledged: "Agent đã xác nhận lệnh",
      time_requested: "Trẻ đã xin thêm giờ", time_request_decided: "Đã trả lời yêu cầu xin giờ",
      child_pin_changed: "Đã đổi PIN hồ sơ"}[a.action] || a.action)
  ), "Chưa có thay đổi.");
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
    const button = event.target.querySelector("button");
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
  const selected = childProfiles.find(row => row.id === el("child-select").value);
  el("child-pin-status").textContent = selected ? (selected.has_pin ? "PIN đã được thiết lập." : "Hồ sơ cũ chưa có PIN; hãy tạo PIN trước khi đăng nhập trên máy trẻ.") : "";
  loadPolicy().catch(e => tell(e.message));
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
