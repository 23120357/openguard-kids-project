import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const RUNTIME_ROOT = "C:/Users/ADMIN/.cache/codex-runtimes/codex-primary-runtime/dependencies";
const SKILL_DIR = "C:/Users/ADMIN/.codex/plugins/cache/openai-primary-runtime/presentations/26.1011.11113/skills/presentations";
const WORKSPACE = "D:/HCMUS/Ki_1_Nam_4/CDMMT/openguard-kids-project";
const BUILD = path.join(WORKSPACE, ".codex-build/week3-technical");
const RENDER = path.join(BUILD, "rendered");
const FINAL = path.join(WORKSPACE, "output/presentation/OpenGuardKids_Tuan3_LuongKyThuat_v2.pptx");

const { Presentation, PresentationFile } = await import(pathToFileURL(path.join(RUNTIME_ROOT, "node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs")).href);
const { makeNativeBulletParagraphs, finalizePresentation } = await import(pathToFileURL(path.join(SKILL_DIR, "container_tools/artifact_tool_utils.mjs")).href);

const W = 1280, H = 720, FONT = "Arial";
const C = {
  navy: "#10354A", navy2: "#1A5368", green: "#1F8A70", mint: "#70D3AE",
  pale: "#E9F5F0", ink: "#17312C", muted: "#5C706A", line: "#D5E4DE",
  paper: "#F7FAF8", white: "#FFFFFF", amber: "#E8A13B", amberPale: "#FFF3DE",
  red: "#C94D52", redPale: "#FFF0F0", bluePale: "#EAF3F7",
};

await fs.mkdir(RENDER, { recursive: true });
await fs.mkdir(path.dirname(FINAL), { recursive: true });

function addShape(slide, geometry, position, fill = "none", line = "none", radius) {
  const supportsRadius = geometry === "rect" || geometry === "textbox" || geometry === "roundRect";
  return slide.shapes.add({
    geometry, position, fill,
    line: { style: "solid", fill: line, width: line === "none" ? 0 : 1 },
    ...(radius && supportsRadius ? { borderRadius: radius } : {}),
  });
}

function addText(slide, text, position, opts = {}) {
  const box = addShape(slide, "textbox", position, "none", "none");
  box.text = text;
  box.text.style = {
    typeface: FONT, fontSize: opts.fontSize ?? 18, bold: opts.bold ?? false,
    color: opts.color ?? C.ink, alignment: opts.alignment ?? "left", autoFit: "shrinkText",
  };
  return box;
}

function addBullets(slide, items, position, opts = {}) {
  const box = addShape(slide, "textbox", position, "none", "none");
  box.text = makeNativeBulletParagraphs(items, {
    marginLeftPoints: opts.marginLeftPoints ?? 18,
    hangingPoints: opts.hangingPoints ?? 9,
    spaceAfterPoints: opts.spaceAfterPoints ?? 9,
  });
  box.text.style = { typeface: FONT, fontSize: opts.fontSize ?? 17, color: opts.color ?? C.ink, autoFit: "shrinkText" };
  return box;
}

function base(pres, title, number, subtitle = "") {
  const slide = pres.slides.add();
  slide.background.fill = C.paper;
  addShape(slide, "rect", { left: 0, top: 0, width: 12, height: H }, C.green, "none");
  addText(slide, "OPEN GUARD KIDS · TUẦN 3", { left: 55, top: 27, width: 360, height: 20 }, { fontSize: 11, bold: true, color: C.green });
  addText(slide, title, { left: 55, top: 57, width: 1110, height: 50 }, { fontSize: 34, bold: true, color: C.navy });
  addText(slide, String(number).padStart(2, "0"), { left: 1172, top: 28, width: 52, height: 18 }, { fontSize: 11, bold: true, color: C.green, alignment: "right" });
  addShape(slide, "rect", { left: 55, top: 118, width: 1170, height: 1 }, C.line, "none");
  if (subtitle) addText(slide, subtitle, { left: 55, top: 134, width: 1120, height: 31 }, { fontSize: 17, color: C.muted });
  return slide;
}

function notes(slide, sourceList, talk = []) {
  slide.speakerNotes.text = [
    "Gợi ý trình bày:", ...talk.map(x => "- " + x), "", "Nguồn:", ...sourceList.map(x => "- " + x),
  ].join("\n");
}

function badge(slide, value, x, y, fill = C.green, width = 38) {
  const s = addShape(slide, "roundRect", { left: x, top: y, width, height: 25 }, fill, "none", "rounded-full");
  s.text = value;
  s.text.style = { typeface: FONT, fontSize: 11, bold: true, color: C.white, alignment: "center", autoFit: "shrinkText" };
  return s;
}

function node(slide, x, y, w, h, title, body = "", opts = {}) {
  const s = addShape(slide, opts.geometry ?? "roundRect", { left: x, top: y, width: w, height: h }, opts.fill ?? C.white, opts.line ?? C.line, "rounded-xl");
  if (opts.geometry === "diamond") {
    s.text = title + (body ? "\n" + body : "");
    s.text.style = { typeface: FONT, fontSize: opts.fontSize ?? 14, bold: true, color: opts.color ?? C.navy, alignment: "center", autoFit: "shrinkText" };
  } else {
    addText(slide, title, { left: x + 14, top: y + 12, width: w - 28, height: 26 }, { fontSize: opts.titleSize ?? 17, bold: true, color: opts.color ?? C.navy, alignment: opts.align ?? "left" });
    if (body) addText(slide, body, { left: x + 14, top: y + 43, width: w - 28, height: h - 52 }, { fontSize: opts.bodySize ?? 13, color: opts.bodyColor ?? C.muted, alignment: opts.align ?? "left" });
  }
  return s;
}

function arrow(slide, x, y, w, h = 25, fill = C.mint, direction = "right") {
  return addShape(slide, direction === "left" ? "leftArrow" : "rightArrow", { left: x, top: y, width: w, height: h }, fill, "none");
}

function actor(slide, x, title, detail = "") {
  node(slide, x, 174, 184, 68, title, detail, { fill: C.white, titleSize: 16, bodySize: 11, align: "center" });
  addShape(slide, "rect", { left: x + 91, top: 242, width: 2, height: 405 }, C.line, "none");
}

function message(slide, fromX, toX, y, label, num, color = C.green) {
  const leftToRight = toX > fromX;
  const start = leftToRight ? fromX + 100 : toX + 100;
  const width = Math.abs(toX - fromX);
  arrow(slide, start, y + 18, width, 20, color, leftToRight ? "right" : "left");
  badge(slide, String(num), start + 4, y - 5, color, 27);
  addText(slide, label, { left: start + 37, top: y - 6, width: Math.max(120, width - 43), height: 31 }, { fontSize: 13, bold: true, color: C.navy, alignment: "center" });
}

function branchLabel(slide, text, x, y, fill, width = 74) {
  const s = addShape(slide, "roundRect", { left: x, top: y, width, height: 24 }, fill, "none", "rounded-full");
  s.text = text;
  s.text.style = { typeface: FONT, fontSize: 11, bold: true, color: C.white, alignment: "center", autoFit: "shrinkText" };
  return s;
}

const pres = Presentation.create({ slideSize: { width: W, height: H } });

// 1 Cover
{
  const s = pres.slides.add();
  s.background.fill = C.navy;
  addShape(s, "rect", { left: 92, top: 91, width: 7, height: 525 }, C.mint, "none");
  addText(s, "OpenGuard Kids", { left: 138, top: 126, width: 420, height: 40 }, { fontSize: 22, bold: true, color: C.mint });
  addText(s, "Luồng hoạt động\nF2 và F3", { left: 138, top: 214, width: 710, height: 150 }, { fontSize: 56, bold: true, color: C.white });
  addText(s, "Báo cáo kỹ thuật Tuần 3", { left: 142, top: 395, width: 510, height: 40 }, { fontSize: 22, color: "#D3E6DF" });
  addShape(s, "ellipse", { left: 964, top: 156, width: 180, height: 180 }, C.green, "none");
  addShape(s, "ellipse", { left: 1021, top: 213, width: 66, height: 66 }, C.navy, "none");
  addText(s, "APP", { left: 936, top: 373, width: 116, height: 38 }, { fontSize: 25, bold: true, color: C.mint, alignment: "center" });
  addText(s, "DNS", { left: 1058, top: 373, width: 116, height: 38 }, { fontSize: 25, bold: true, color: C.mint, alignment: "center" });
  addText(s, "12.10.2026", { left: 142, top: 585, width: 220, height: 24 }, { fontSize: 14, bold: true, color: "#9CC7B8" });
  notes(s, ["Mã nguồn và tài liệu OpenGuard Kids tại mốc 12/10/2026"], ["Mở đầu bằng hai luồng chính: chặn ứng dụng và chặn website qua DNS proxy."]);
}

// 2 System overview
{
  const s = base(pres, "Kiến trúc thực thi chính sách", 2, "Dashboard cấu hình luật; Agent Service chịu trách nhiệm thực thi trên máy trẻ.");
  node(s, 55, 202, 205, 135, "Dashboard phụ huynh", "Chọn hồ sơ\nCấu hình app/web\nXem sự kiện và báo cáo", { fill: C.white, align: "center" });
  arrow(s, 272, 250, 74, 28, C.mint);
  node(s, 360, 202, 205, 135, "FastAPI server", "Lưu policy theo version\nKý HMAC theo thiết bị\nNhận event batch", { fill: C.bluePale, line: C.navy2, align: "center" });
  arrow(s, 578, 250, 74, 28, C.mint);
  node(s, 666, 202, 205, 135, "Windows Service", "Xác minh policy\nApp Controller\nDNS proxy + outbox", { fill: C.pale, line: C.green, align: "center" });
  arrow(s, 884, 250, 74, 28, C.mint);
  node(s, 972, 202, 205, 135, "Tray của trẻ", "Đăng nhập hồ sơ\nHeartbeat hiện diện\nPopup lý do chặn", { fill: C.white, align: "center" });
  addText(s, "Kênh cấu hình", { left: 287, top: 222, width: 55, height: 40 }, { fontSize: 11, bold: true, color: C.green, alignment: "center" });
  addText(s, "Policy đã ký", { left: 590, top: 222, width: 59, height: 40 }, { fontSize: 11, bold: true, color: C.green, alignment: "center" });
  addText(s, "Named pipe", { left: 894, top: 222, width: 59, height: 40 }, { fontSize: 11, bold: true, color: C.green, alignment: "center" });
  node(s, 300, 410, 225, 111, "SQLite server", "Policy, event, generation, audit", { fill: C.white, align: "center" });
  node(s, 705, 410, 225, 111, "SQLite tại agent", "Outbox, history, policy cache", { fill: C.white, align: "center" });
  arrow(s, 410, 353, 26, 51, C.navy2, "right");
  arrow(s, 815, 353, 26, 51, C.green, "right");
  addShape(s, "roundRect", { left: 55, top: 584, width: 1122, height: 64 }, C.amberPale, "none", "rounded-xl");
  addText(s, "Điều kiện thực thi: trẻ đã đăng nhập, Tray còn heartbeat và policy tương ứng đang bật. Nếu thiếu Tray, hệ thống không âm thầm thu thập hoặc chặn.", { left: 79, top: 602, width: 1074, height: 33 }, { fontSize: 16, bold: true, color: "#7B571D", alignment: "center" });
  notes(s, ["docs/ARCHITECTURE.md", "docs/WEEK3_EVENTS.md", "agent/remote_sync.py", "agent/core.py"], ["Nhấn mạnh ranh giới: server quản lý chính sách, Service thực thi, Tray đại diện phiên người dùng.", "Policy và event dùng hai chiều dữ liệu khác nhau."]);
}

// 3 Policy lifecycle
{
  const s = base(pres, "Vòng đời chính sách app và web", 3, "Version và HMAC ngăn agent áp dụng policy sai thiết bị hoặc bị sửa trên đường truyền.");
  const xs = [60, 300, 540, 780, 1020];
  const titles = ["Phụ huynh lưu", "Server kiểm tra", "Server ký", "Agent xác minh", "Agent áp dụng"];
  const bodies = [
    "Gửi expected_version\n+ CSRF token", "Kiểm tra quyền sở hữu\nvà xung đột version", "Gắn device_id\nHMAC-SHA256", "Đúng device_id\nChữ ký hợp lệ", "Cập nhật core\nvà lưu cache offline",
  ];
  xs.forEach((x, i) => {
    badge(s, String(i + 1), x + 8, 204, i === 3 ? C.navy2 : C.green, 30);
    node(s, x, 243, 185, 145, titles[i], bodies[i], { fill: i === 3 ? C.bluePale : C.white, line: i === 3 ? C.navy2 : C.line, align: "center", titleSize: 16 });
    if (i < xs.length - 1) arrow(s, x + 190, 300, 43, 24, C.mint);
  });
  addText(s, "Nếu chữ ký hoặc device_id sai", { left: 655, top: 439, width: 270, height: 28 }, { fontSize: 16, bold: true, color: C.red, alignment: "center" });
  arrow(s, 726, 398, 25, 35, C.red);
  node(s, 662, 482, 262, 82, "Từ chối policy", "Giữ policy cache hợp lệ trước đó và ghi lỗi trạng thái", { fill: C.redPale, line: C.red, align: "center", titleSize: 17, color: C.red, bodyColor: "#8E4447" });
  addShape(s, "roundRect", { left: 60, top: 609, width: 1120, height: 45 }, C.pale, "none", "rounded-xl");
  addText(s, "Policy ứng dụng và web được đồng bộ trong vòng activity sync 5 giây; cache cho phép agent giữ luật gần nhất khi server tạm mất kết nối.", { left: 82, top: 620, width: 1075, height: 24 }, { fontSize: 15, bold: true, color: C.green, alignment: "center" });
  notes(s, ["agent/remote_sync.py::_configure_filtering", "server/app/event_routes.py::device_filtering", "common/policy_security.py"], ["Giải thích optimistic concurrency bằng expected_version.", "HMAC không thay thế TLS, nhưng giúp agent phát hiện policy bị sửa hoặc gửi nhầm thiết bị."]);
}

// 4 App block sequence
{
  const s = base(pres, "Luồng chặn ứng dụng", 4, "App Controller chỉ xét tiến trình trong cùng Windows session với Tray của trẻ.");
  const xs = [46, 292, 538, 784, 1030];
  actor(s, xs[0], "Dashboard", "phụ huynh");
  actor(s, xs[1], "Server", "policy + HMAC");
  actor(s, xs[2], "Agent Service", "App Controller");
  actor(s, xs[3], "Windows", "process của trẻ");
  actor(s, xs[4], "Tray / Event", "lý do + lịch sử");
  message(s, xs[0], xs[1], 258, "Lưu rule {name, SHA-256}", 1);
  message(s, xs[1], xs[2], 330, "Đồng bộ policy đã ký", 2);
  message(s, xs[2], xs[3], 402, "Quét process mỗi 1 giây", 3, C.navy2);
  message(s, xs[3], xs[2], 474, "PID, create_time, exe path", 4, C.navy2);
  message(s, xs[2], xs[3], 546, "Hash khớp blocklist: kill", 5, C.red);
  message(s, xs[2], xs[4], 608, "blocked_app + reason", 6, C.green);
  notes(s, ["agent/filtering.py::AppController.scan", "agent/filtering.py::app_decision", "docs/WEEK3_EVENTS.md"], ["Bước 4: Service tự đọc file và tính SHA-256, đường dẫn không gửi lên server.", "Trước khi kill, Service đọc lại create_time và exe path để tránh lỗi PID bị tái sử dụng.", "Sau khi chặn, cùng một reason đi tới popup Tray và lịch sử dashboard."]);
}

// 5 App decision tree
{
  const s = base(pres, "Cây quyết định kiểm soát ứng dụng", 5, "Tên giúp phụ huynh nhận biết; SHA-256 mới là căn cứ ra quyết định.");
  node(s, 70, 185, 225, 72, "Có activity context?", "Trẻ đăng nhập + Tray hiện diện", { geometry: "diamond", fill: C.bluePale, line: C.navy2, fontSize: 14 });
  arrow(s, 300, 208, 100, 25, C.red);
  branchLabel(s, "KHÔNG", 310, 178, C.red);
  node(s, 415, 184, 205, 75, "Dừng xử lý", "Không quét và xóa trạng thái seen", { fill: C.redPale, line: C.red, align: "center", color: C.red });
  arrow(s, 165, 263, 26, 47, C.green);
  branchLabel(s, "CÓ", 202, 274, C.green, 52);
  node(s, 70, 319, 225, 72, "Protected Windows process?", "Tên + vị trí Windows tin cậy", { geometry: "diamond", fill: C.white, line: C.line, fontSize: 14 });
  arrow(s, 300, 342, 100, 25, C.amber);
  branchLabel(s, "CÓ", 312, 312, C.amber, 52);
  node(s, 415, 318, 205, 75, "Bỏ qua", "Không terminate thành phần giao diện Windows", { fill: C.amberPale, line: C.amber, align: "center", color: "#8D641F" });
  arrow(s, 165, 398, 26, 44, C.green);
  branchLabel(s, "KHÔNG", 202, 407, C.green);
  node(s, 70, 452, 225, 72, "Hash nằm trong app_block?", "Blocklist ưu tiên", { geometry: "diamond", fill: C.white, line: C.line, fontSize: 14 });
  arrow(s, 300, 475, 100, 25, C.red);
  branchLabel(s, "CÓ", 312, 445, C.red, 52);
  node(s, 415, 451, 205, 75, "BLOCK", "Kiểm tra lại identity rồi kill + event", { fill: C.redPale, line: C.red, align: "center", color: C.red });
  arrow(s, 165, 530, 26, 43, C.green);
  branchLabel(s, "KHÔNG", 202, 538, C.green);
  node(s, 70, 582, 225, 72, "Allowlist mode và hash chưa allow?", "", { geometry: "diamond", fill: C.white, line: C.line, fontSize: 13 });
  arrow(s, 300, 605, 100, 25, C.red);
  branchLabel(s, "CÓ", 312, 575, C.red, 52);
  node(s, 415, 581, 205, 75, "BLOCK", "Ứng dụng không nằm trong danh sách cho phép", { fill: C.redPale, line: C.red, align: "center", color: C.red });
  arrow(s, 628, 605, 80, 25, C.green);
  branchLabel(s, "KHÔNG", 633, 575, C.green);
  node(s, 723, 563, 230, 93, "ALLOW", "Ghi app_start/app_stop để tính thời lượng", { fill: C.pale, line: C.green, align: "center", color: C.green });
  node(s, 989, 318, 205, 184, "Vì sao dùng hash?", "Đổi tên game.exe thành explorer.exe không làm thay đổi hash.\n\nPhiên bản ứng dụng mới có hash khác, nên phụ huynh phải xem lại rule.", { fill: C.navy, line: C.navy, titleSize: 19, bodySize: 14, color: C.white, bodyColor: "#D7E8E2" });
  notes(s, ["agent/filtering.py::app_decision", "agent/filtering.py::trusted_windows_process", "tests/test_f2_filtering.py"], ["Blocklist luôn được kiểm tra trước allowlist.", "Tên protected chỉ được miễn nếu executable thật nằm trong thư mục Windows tin cậy."]);
}

// 6 Web protection activation
{
  const s = base(pres, "Luồng kích hoạt DNS proxy trên Windows", 6, "Service chỉ đổi DNS sau khi proxy UDP và TCP đã bind thành công trên IPv4 và IPv6 loopback.");
  const steps = [
    ["1", "Đủ điều kiện", "Trẻ đăng nhập\nTray heartbeat\nDNS proxy bật"],
    ["2", "Khởi động proxy", "127.0.0.1:53\n[::1]:53\nUDP + TCP"],
    ["3", "Sao lưu", "DNS từng adapter\nChrome/Edge/Firefox\nSecure DNS policy"],
    ["4", "Cấu hình", "DNS máy về loopback\nTắt DoH trình duyệt\nđược hỗ trợ"],
    ["5", "Theo dõi", "Kiểm tra lại mỗi 10 giây\nvà bắt adapter mới"],
  ];
  steps.forEach((item, i) => {
    const x = 55 + i * 240;
    badge(s, item[0], x + 10, 202, i === 3 ? C.navy2 : C.green, 30);
    node(s, x, 242, 188, 164, item[1], item[2], { fill: i === 2 ? C.amberPale : C.white, line: i === 2 ? C.amber : C.line, align: "center", titleSize: 17 });
    if (i < 4) arrow(s, x + 192, 310, 42, 24, C.mint);
  });
  addText(s, "Tắt bảo vệ / đăng xuất / dừng service", { left: 135, top: 481, width: 330, height: 30 }, { fontSize: 18, bold: true, color: C.red, alignment: "center" });
  arrow(s, 469, 485, 104, 24, C.red);
  node(s, 590, 456, 320, 87, "Khôi phục cấu hình gốc", "DNS tĩnh hoặc DHCP và browser policy cũ từ network-backup.json", { fill: C.redPale, line: C.red, align: "center", titleSize: 18, color: C.red, bodyColor: "#8B4548" });
  addShape(s, "roundRect", { left: 55, top: 597, width: 1138, height: 54 }, C.pale, "none", "rounded-xl");
  addText(s, "Nếu cấu hình lỗi, Service cố gắng rollback và giữ backup để thử khôi phục lại. Cleanup từ chối xóa runtime khi DNS chưa phục hồi an toàn.", { left: 82, top: 612, width: 1085, height: 29 }, { fontSize: 15, bold: true, color: C.green, alignment: "center" });
  notes(s, ["docs/WEB_PROTECTION.md", "agent/web_protection.py", "agent/windows_service.py"], ["Đây là cấu hình cấp máy, nên ảnh hưởng mọi user trong lúc bật.", "Backup không bị ghi đè sau restart, giúp có điểm khôi phục ổn định."]);
}

// 7 DNS query flow
{
  const s = base(pres, "Luồng chặn website qua DNS proxy", 7, "Proxy trả NXDOMAIN khi rule quyết định chặn; trình duyệt không nhận được IP của website.");
  const xs = [46, 292, 538, 784, 1030];
  actor(s, xs[0], "Trình duyệt", "Chrome / Edge / Firefox");
  actor(s, xs[1], "Windows DNS", "adapter dùng loopback");
  actor(s, xs[2], "DNS Proxy", "127.0.0.1:53");
  actor(s, xs[3], "Upstream", "1.1.1.1 mặc định");
  actor(s, xs[4], "Event / Tray", "SQLite outbox + popup");
  message(s, xs[0], xs[1], 262, "Query A / AAAA / CNAME", 1);
  message(s, xs[1], xs[2], 334, "Chuyển query về loopback", 2);
  message(s, xs[2], xs[4], 406, "domain_query, gộp trong 5 giây", 3, C.navy2);
  message(s, xs[2], xs[0], 480, "Nếu BLOCK: trả NXDOMAIN", 4, C.red);
  message(s, xs[2], xs[4], 552, "blocked_domain + reason", 5, C.red);
  message(s, xs[2], xs[3], 616, "Nếu ALLOW: hỏi upstream hoặc SafeSearch", 6, C.green);
  notes(s, ["agent/filtering.py::DNSProxy.resolve", "agent/filtering.py::domain_decision", "docs/F2_TESTING.md"], ["A/AAAA/retry gần nhau chỉ tạo một domain_query và một blocked_domain trong cửa sổ 5 giây.", "NXDOMAIN làm browser dừng trước bước kết nối HTTPS, nên hệ thống không cần đọc nội dung trang."]);
}

// 8 DNS decision order
{
  const s = base(pres, "Thứ tự quyết định của DNS proxy", 8, "Thứ tự ưu tiên tránh trường hợp category vô tình chặn miền trường học hoặc hỗ trợ khẩn cấp.");
  const decisions = [
    ["1", "Policy hoặc DNS proxy đang tắt?", "FORWARD", C.navy2, "Không áp dụng rule"],
    ["2", "Safety domain hoặc tongdai111.vn?", "ALLOW", C.green, "Ưu tiên cao nhất"],
    ["3", "Khớp domain_block?", "BLOCK", C.red, "Trả NXDOMAIN"],
    ["4", "Allowlist mode nhưng chưa allow?", "BLOCK", C.red, "Trả NXDOMAIN"],
    ["5", "Khớp domain_allow?", "ALLOW", C.green, "Bỏ qua category"],
    ["6", "Category action = block?", "BLOCK", C.red, "Trả NXDOMAIN"],
    ["7", "Google/Bing + SafeSearch bật?", "REWRITE", C.amber, "CNAME tới safe endpoint"],
    ["8", "Còn lại", "FORWARD", C.navy2, "Upstream DNS"],
  ];
  decisions.forEach((d, i) => {
    const col = i < 4 ? 0 : 1;
    const row = i % 4;
    const x = col ? 650 : 60;
    const y = 184 + row * 116;
    badge(s, d[0], x, y + 8, d[3], 31);
    addText(s, d[1], { left: x + 48, top: y + 4, width: 350, height: 36 }, { fontSize: 17, bold: true, color: C.navy });
    branchLabel(s, d[2], x + 405, y + 3, d[3], d[2] === "FORWARD" ? 98 : d[2] === "REWRITE" ? 92 : 75);
    addText(s, d[4], { left: x + 48, top: y + 48, width: 430, height: 25 }, { fontSize: 14, color: C.muted });
    if (row < 3) addShape(s, "rect", { left: x + 48, top: y + 91, width: 485, height: 1 }, C.line, "none");
  });
  addShape(s, "rect", { left: 620, top: 177, width: 1, height: 468 }, C.line, "none");
  addShape(s, "roundRect", { left: 60, top: 648, width: 1120, height: 35 }, C.amberPale, "none", "rounded-xl");
  addText(s, "Upstream timeout hoặc phản hồi không khớp query sẽ trả SERVFAIL, không âm thầm bỏ SafeSearch hoặc dùng DNS khác.", { left: 84, top: 655, width: 1070, height: 22 }, { fontSize: 14, bold: true, color: "#7C591F", alignment: "center" });
  notes(s, ["agent/filtering.py::domain_decision", "agent/filtering.py::DNSProxy.resolve", "agent/filtering.py::safe_search_reply"], ["Đi từ dòng 1 đến dòng 8 và dừng ở kết quả đầu tiên phù hợp.", "Explicit allow bỏ qua category nhưng SafeSearch vẫn áp dụng sau đó."]);
}

// 9 Offline event sync and delete
{
  const s = base(pres, "Đồng bộ sự kiện offline và chống trùng", 9, "UUID được tạo một lần tại agent và giữ nguyên qua mọi lần retry.");
  node(s, 55, 195, 202, 105, "1. Ghi local", "Event + explanation\nđược lưu SQLite outbox", { fill: C.white, align: "center" });
  arrow(s, 267, 234, 54, 25, C.mint);
  node(s, 332, 195, 202, 105, "2. Đọc generation", "GET /device/event-state\ntrước khi upload", { fill: C.bluePale, line: C.navy2, align: "center" });
  arrow(s, 544, 234, 54, 25, C.mint);
  node(s, 609, 195, 202, 105, "3. Gửi batch", "Tối đa 100 event\nUUID không đổi khi retry", { fill: C.pale, line: C.green, align: "center" });
  arrow(s, 821, 234, 54, 25, C.mint);
  node(s, 886, 195, 290, 105, "4. Server ACK", "Insert mới hoặc trả ACK cho UUID đã có\n409 nếu cùng UUID nhưng payload khác", { fill: C.white, align: "center" });
  addText(s, "Khi phụ huynh yêu cầu xóa dữ liệu", { left: 55, top: 366, width: 420, height: 33 }, { fontSize: 22, bold: true, color: C.navy });
  node(s, 55, 422, 230, 104, "Server tăng generation", "Xóa event và dữ liệu báo cáo trong cùng transaction", { fill: C.redPale, line: C.red, align: "center", color: C.red });
  arrow(s, 296, 462, 56, 25, C.red);
  node(s, 364, 422, 230, 104, "Agent kết nối lại", "Thấy generation mới và xóa history + outbox cũ", { fill: C.amberPale, line: C.amber, align: "center", color: "#8A621E" });
  arrow(s, 605, 462, 56, 25, C.red);
  node(s, 673, 422, 230, 104, "Agent ACK", "POST event-state/ack sau khi commit local", { fill: C.pale, line: C.green, align: "center", color: C.green });
  arrow(s, 914, 462, 56, 25, C.red);
  node(s, 982, 422, 194, 104, "Hoàn tất", "Dashboard hết trạng thái đang chờ thiết bị", { fill: C.white, align: "center" });
  addShape(s, "roundRect", { left: 55, top: 596, width: 1121, height: 52 }, C.pale, "none", "rounded-xl");
  addText(s, "Event thuộc generation cũ bị discard kể cả khi đến server sau yêu cầu xóa, nên dữ liệu đã xóa không xuất hiện trở lại.", { left: 80, top: 610, width: 1072, height: 29 }, { fontSize: 15, bold: true, color: C.green, alignment: "center" });
  notes(s, ["agent/remote_sync.py::sync_activity", "server/app/event_routes.py::ingest_events", "docs/WEEK3_EVENTS.md"], ["Mất response sau commit không tạo bản ghi thứ hai vì agent retry cùng UUID.", "Generation đóng vai trò hàng rào giữa dữ liệu cũ và dữ liệu sau yêu cầu xóa."]);
}

// 10 Reporting pipeline
{
  const s = base(pres, "Luồng tổng hợp báo cáo hoạt động", 10, "Dashboard và Tray dùng cùng hàm tổng hợp để số liệu có cùng ý nghĩa.");
  node(s, 55, 204, 220, 122, "Sự kiện đầu vào", "app_stop + duration\ndomain_query\nblocked_app / blocked_domain", { fill: C.white, align: "center" });
  arrow(s, 285, 251, 62, 25, C.mint);
  node(s, 360, 204, 250, 122, "activity_report()", "Cắt theo UTC+7\nchia đoạn qua nửa đêm\ngom theo ngày và tuần", { fill: C.pale, line: C.green, align: "center" });
  arrow(s, 620, 251, 62, 25, C.mint);
  node(s, 695, 204, 220, 122, "Dữ liệu dẫn xuất", "total duration\nblocked count\ntop apps + top domains", { fill: C.bluePale, line: C.navy2, align: "center" });
  arrow(s, 925, 251, 62, 25, C.mint);
  node(s, 1000, 204, 220, 122, "Đầu ra", "Dashboard\nTray Hôm nay\nPDF / CSV", { fill: C.white, align: "center" });
  addText(s, "Cách hiểu đúng số liệu", { left: 55, top: 394, width: 350, height: 34 }, { fontSize: 23, bold: true, color: C.navy });
  const meanings = [
    ["Thời gian dùng máy", "Chỉ tính khi Tray hiện diện, trẻ đăng nhập, máy không khóa và không idle quá ngưỡng."],
    ["Top ứng dụng", "Tổng thời gian process chạy; ứng dụng có thể chạy nền hoặc chạy cùng lúc."],
    ["Top tên miền", "Số lượt DNS đã gộp trong cửa sổ 5 giây; không phải số lần mở trang."],
  ];
  meanings.forEach((m, i) => {
    const x = 55 + i * 390;
    badge(s, String(i + 1), x, 460, i === 1 ? C.navy2 : C.green, 31);
    addText(s, m[0], { left: x + 48, top: 456, width: 280, height: 30 }, { fontSize: 18, bold: true, color: C.navy });
    addText(s, m[1], { left: x + 48, top: 498, width: 315, height: 94 }, { fontSize: 15, color: C.muted });
  });
  notes(s, ["common/activity_reports.py", "server/app/event_routes.py", "dashboard/static/app.js", "agent/tray_ui.py"], ["Giải thích app_stop: duration mô tả đoạn thời gian ngay trước event.", "Biểu đồ ngày luôn 7 ngày, biểu đồ tuần lấy 56 ngày rồi gom thành 8 tuần."]);
}

// 11 End-to-end demo
{
  const s = base(pres, "Kịch bản demo xuyên suốt để trình bày", 11, "Mỗi bước demo liên hệ trực tiếp với một sơ đồ kỹ thuật trong bộ slide.");
  const rows = [
    ["1", "Lưu policy", "Chọn ứng dụng đã phát hiện và thêm example.com vào blocklist.", "Slide 3"],
    ["2", "Chặn app", "Mở executable lab, quan sát process bị kill và popup lý do.", "Slide 4–5"],
    ["3", "Chặn web", "Mở example.com, browser nhận lỗi DNS và Tray ghi blocked_domain.", "Slide 6–8"],
    ["4", "Mất mạng", "Dừng server, tạo event rồi bật lại để chứng minh retry không nhân đôi.", "Slide 9"],
    ["5", "Báo cáo", "Mở báo cáo, giải thích 7 ngày, 8 tuần, top app/domain và xuất PDF.", "Slide 10"],
  ];
  rows.forEach((r, i) => {
    const y = 182 + i * 90;
    badge(s, r[0], 62, y + 5, i % 2 ? C.navy2 : C.green, 31);
    addText(s, r[1], { left: 115, top: y, width: 175, height: 34 }, { fontSize: 20, bold: true, color: C.navy });
    addText(s, r[2], { left: 305, top: y, width: 710, height: 47 }, { fontSize: 16, color: C.ink });
    branchLabel(s, r[3], 1050, y + 3, i % 2 ? C.navy2 : C.green, 120);
    if (i < rows.length - 1) addShape(s, "rect", { left: 115, top: y + 65, width: 1055, height: 1 }, C.line, "none");
  });
  addShape(s, "roundRect", { left: 62, top: 639, width: 1108, height: 40 }, C.amberPale, "none", "rounded-xl");
  addText(s, "Chỉ dùng executable và domain lab; không thử terminate ứng dụng có dữ liệu chưa lưu và không tìm nội dung không phù hợp để test SafeSearch.", { left: 84, top: 647, width: 1065, height: 24 }, { fontSize: 14, bold: true, color: "#7C591F", alignment: "center" });
  notes(s, ["docs/F2_TESTING.md", "docs/F3_REPORTS.md", "docs/WEEK3_EVENTS.md"], ["Demo theo thứ tự từ cấu hình đến thực thi rồi mới tới báo cáo.", "Dừng ở mỗi bước để chỉ actor và dữ liệu tương ứng trên sơ đồ."]);
}

// 12 Evidence and limits
{
  const s = base(pres, "Kiểm chứng và giới hạn hiện tại", 12, "Bộ test chứng minh logic phần mềm; nghiệm thu Windows thật vẫn cần thực hiện trên máy lab độc lập.");
  addText(s, "Bằng chứng", { left: 62, top: 180, width: 330, height: 36 }, { fontSize: 24, bold: true, color: C.navy });
  addBullets(s, [
    "179 pytest đạt tại mốc 09/10/2026.",
    "108 test F2/F3/Tray đạt tại mốc 11/10/2026.",
    "DNS isolated đạt 50/50 miền chặn và 20/20 miền giáo dục.",
    "480 truy vấn A/AAAA qua UDP/TCP đều đạt kỳ vọng.",
    "Dashboard regression trên Edge headless đạt.",
  ], { left: 62, top: 235, width: 485, height: 300 }, { fontSize: 18, spaceAfterPoints: 12 });
  addShape(s, "rect", { left: 617, top: 178, width: 1, height: 385 }, C.line, "none");
  addText(s, "Giới hạn", { left: 674, top: 180, width: 330, height: 36 }, { fontSize: 24, bold: true, color: C.navy });
  addBullets(s, [
    "DoH/DoT, VPN, IP trực tiếp và DNS cache vẫn có thể vượt bộ lọc.",
    "Chưa có WFP/firewall và chưa xử lý nhiều phiên Windows đồng thời.",
    "Dataset 311 miền cần người rà soát trước khi tuyên bố độ an toàn nội dung.",
    "Cần nghiệm thu terminate app, DNS adapter, browser policy và khóa máy trên Windows thật.",
  ], { left: 674, top: 235, width: 505, height: 300 }, { fontSize: 18, spaceAfterPoints: 12 });
  addShape(s, "roundRect", { left: 62, top: 606, width: 1117, height: 53 }, C.navy, "none", "rounded-xl");
  addText(s, "Kết luận: kiến trúc và các luồng chính đã khép kín trong môi trường lab; bước tiếp theo tập trung vào chống bypass và nghiệm thu hệ điều hành thật.", { left: 88, top: 620, width: 1065, height: 29 }, { fontSize: 16, bold: true, color: C.white, alignment: "center" });
  notes(s, ["docs/WEEK3_EVENTS.md", "docs/F2_TESTING.md", "output/f2-dns.json", "docs/WEB_PROTECTION.md"], ["Không đánh đồng test isolated với nghiệm thu production.", "Chủ động nêu giới hạn trước khi thầy hỏi về DoH, VPN và quyền admin của trẻ."]);
}

for (const [i, slide] of pres.slides.items.entries()) {
  const png = await pres.export({ slide, format: "png", scale: 1 });
  await fs.writeFile(path.join(RENDER, `slide-${String(i + 1).padStart(2, "0")}.png`), new Uint8Array(await png.arrayBuffer()));
}

const staging = path.join(BUILD, "finalizer");
await fs.mkdir(staging, { recursive: true });
const candidate = path.join(staging, "candidate-technical.pptx");
await (await PresentationFile.exportPptx(pres)).save(candidate);

const result = await finalizePresentation({
  explicitTotalSlideCount: 12,
  requiredNativeTableOwnerSlides: [], requiredNativeChartOwnerSlides: [],
  workspaceDir: WORKSPACE, candidatePath: candidate, finalPath: FINAL,
  pythonExecutable: path.join(RUNTIME_ROOT, "python/python.exe"),
  integrityValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: ["--expected-slide-size-emu", "12192000,6858000", "--validate-bullet-geometry", "--validate-heading-fit"],
  fontPolicy: { basis: "design", families: [FONT] }, verifyArtifactToolImport: true,
  receiptPath: path.join(staging, "OpenGuardKids_Tuan3_LuongKyThuat_v2.validation.json"),
});
console.log(JSON.stringify({ final: FINAL, slides: pres.slides.items.length, result }, null, 2));
