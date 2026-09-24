"use strict";
let csrf = "";
let currentPolicy = null;
const el = (id) => document.getElementById(id);
const tell = (message) => { el("message").textContent = message; };

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
  csrf = ""; currentPolicy = null;
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
  el("policy-form").elements.weekday_minutes.value = policy.weekday_minutes;
  el("policy-form").elements.weekend_minutes.value = policy.weekend_minutes;
  el("policy-version").textContent = "Phiên bản " + policy.version;
}
async function loadChildren() {
  const rows = await api("/children");
  const oldId = el("child-select").value;
  el("child-select").replaceChildren(...rows.map(row => new Option(row.display_name, row.id)));
  if (rows.some(row => row.id === oldId)) el("child-select").value = oldId;
  await loadPolicy();
}
function renderList(id, lines, empty) {
  el(id).replaceChildren(...(lines.length ? lines : [empty]).map(line => {
    const li = document.createElement("li"); li.textContent = line; return li;
  }));
}
async function refreshStatus() {
  const [devices, audits] = await Promise.all([api("/devices"), api("/audit")]);
  renderList("devices", devices.map(d =>
    d.display_name + " · " + (d.online ? "Trực tuyến" : "Ngoại tuyến") +
    " · Policy v" + d.policy_version + " · " +
    (d.last_seen ? new Date(d.last_seen * 1000).toLocaleString("vi-VN") : "Chưa gửi heartbeat")
  ), "Chưa có thiết bị. Hãy tạo mã ghép đôi.");
  renderList("audit", audits.slice(0, 10).map(a =>
    new Date(a.ts * 1000).toLocaleString("vi-VN") + " · " +
    (a.action === "policy_updated" ? "Đã cập nhật chính sách" : "Đã đồng ý ghép thiết bị")
  ), "Chưa có thay đổi.");
}
async function enterWorkspace(user) {
  csrf = user.csrf_token; el("identity").textContent = user.email;
  el("login-panel").hidden = true; el("workspace").hidden = false;
  await loadChildren(); await refreshStatus();
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
  await api("/children", "POST", Object.fromEntries(data));
  el("child-form").reset(); await loadChildren(); tell("Đã tạo hồ sơ.");
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
    weekday_minutes: Number(data.get("weekday_minutes")),
    weekend_minutes: Number(data.get("weekend_minutes")),
  });
  currentPolicy = result;
  el("policy-version").textContent = "Phiên bản " + result.version;
  tell("Đã lưu. Agent sẽ nhận cấu hình ở heartbeat tiếp theo.");
  await refreshStatus();
});
el("child-select").addEventListener("change", () => loadPolicy().catch(e => tell(e.message)));
el("logout").addEventListener("click", async () => {
  try { await api("/auth/logout", "POST", {}); showLogin(); tell(""); }
  catch (e) { tell(e.message); }
});
setInterval(() => { if (csrf) refreshStatus().catch(e => tell(e.message)); }, 10000);
api("/auth/me").then(enterWorkspace).catch(() => showLogin());
