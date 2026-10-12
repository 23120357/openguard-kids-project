import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const RUNTIME_ROOT = "C:/Users/ADMIN/.cache/codex-runtimes/codex-primary-runtime/dependencies";
const SKILL_DIR = "C:/Users/ADMIN/.codex/plugins/cache/openai-primary-runtime/presentations/26.1011.11113/skills/presentations";
const WORKSPACE = "D:/HCMUS/Ki_1_Nam_4/CDMMT/openguard-kids-project";
const BUILD = path.join(WORKSPACE, ".codex-build/week3");
const RENDER = path.join(BUILD, "rendered");
const FINAL = path.join(WORKSPACE, "output/presentation/OpenGuardKids_BaoCao_Tuan3_2026-10-12_v2.pptx");

const artifactTool = await import(pathToFileURL(path.join(RUNTIME_ROOT, "node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs")).href);
const { Presentation, PresentationFile } = artifactTool;
const { makeNativeBulletParagraphs, finalizePresentation } = await import(pathToFileURL(path.join(SKILL_DIR, "container_tools/artifact_tool_utils.mjs")).href);

const W = 1280;
const H = 720;
const C = {
  navy: "#10354A",
  navy2: "#174B5D",
  green: "#1F8A70",
  mint: "#75D5B1",
  pale: "#EAF6F1",
  ink: "#17312C",
  muted: "#5D716B",
  line: "#D9E6E1",
  paper: "#F7FAF8",
  white: "#FFFFFF",
  amber: "#E6A23C",
  red: "#C74B50",
};
const FONT = "Arial";

await fs.mkdir(RENDER, { recursive: true });
await fs.mkdir(path.dirname(FINAL), { recursive: true });
const SCREEN_APP = await fs.readFile(path.join(WORKSPACE, "output/app-catalog-improved.png"));
const SCREEN_F2 = await fs.readFile(path.join(WORKSPACE, "output/f2-dashboard.png"));
const SCREEN_REPORT = await fs.readFile(path.join(WORKSPACE, "output/reports-charts-final.png"));

function shape(slide, geometry, position, fill = "none", line = "none", radius) {
  return slide.shapes.add({
    geometry,
    position,
    fill,
    line: { style: "solid", fill: line, width: line === "none" ? 0 : 1 },
    ...(radius ? { borderRadius: radius } : {}),
  });
}

function textBox(slide, text, position, style = {}) {
  const box = shape(slide, "textbox", position, "none", "none");
  box.text = text;
  box.text.style = {
    typeface: FONT,
    fontSize: style.fontSize ?? 20,
    bold: style.bold ?? false,
    color: style.color ?? C.ink,
    alignment: style.alignment ?? "left",
    autoFit: "shrinkText",
  };
  return box;
}

function bullets(slide, items, position, options = {}) {
  const box = shape(slide, "textbox", position, "none", "none");
  box.text = makeNativeBulletParagraphs(items, {
    marginLeftPoints: options.marginLeftPoints ?? 18,
    hangingPoints: options.hangingPoints ?? 9,
    spaceAfterPoints: options.spaceAfterPoints ?? 10,
  });
  box.text.style = {
    typeface: FONT,
    fontSize: options.fontSize ?? 19,
    color: options.color ?? C.ink,
    autoFit: "shrinkText",
  };
  return box;
}

function baseSlide(presentation, title, number, section = "BÁO CÁO TIẾN ĐỘ TUẦN 3") {
  const slide = presentation.slides.add();
  slide.background.fill = C.paper;
  shape(slide, "rect", { left: 0, top: 0, width: 12, height: H }, C.green, "none");
  textBox(slide, section, { left: 54, top: 28, width: 420, height: 22 }, { fontSize: 11, bold: true, color: C.green });
  textBox(slide, title, { left: 54, top: 57, width: 1080, height: 54 }, { fontSize: 34, bold: true, color: C.navy });
  shape(slide, "rect", { left: 54, top: 119, width: 1172, height: 1 }, C.line, "none");
  textBox(slide, String(number).padStart(2, "0"), { left: 1167, top: 29, width: 58, height: 20 }, { fontSize: 11, bold: true, color: C.green, alignment: "right" });
  return slide;
}

function addNotes(slide, sources) {
  slide.speakerNotes.text = "Nguồn:\n" + sources.map(item => "- " + item).join("\n");
}

function addScreenshot(slide, bytes, alt, position, crop = { left: 0, top: 0, right: 0, bottom: 0 }) {
  shape(slide, "roundRect", { left: position.left - 5, top: position.top - 5, width: position.width + 10, height: position.height + 10 }, C.white, C.line, "rounded-xl");
  return slide.images.add({
    blob: bytes,
    contentType: "image/png",
    alt,
    fit: "cover",
    crop,
    geometry: "roundRect",
    borderRadius: "rounded-xl",
    position,
  });
}

function label(slide, value, x, y, color = C.green) {
  const pill = shape(slide, "roundRect", { left: x, top: y, width: 46, height: 28 }, color, "none", "rounded-full");
  pill.text = value;
  pill.text.style = { typeface: FONT, fontSize: 13, bold: true, color: C.white, alignment: "center", autoFit: "shrinkText" };
  return pill;
}

const presentation = Presentation.create({ slideSize: { width: W, height: H } });

// 1. Cover
{
  const slide = presentation.slides.add();
  slide.background.fill = C.navy;
  shape(slide, "rect", { left: 92, top: 98, width: 7, height: 500 }, C.mint, "none");
  textBox(slide, "OpenGuard Kids", { left: 134, top: 126, width: 550, height: 54 }, { fontSize: 22, bold: true, color: C.mint });
  textBox(slide, "Báo cáo tiến độ\nTuần 3", { left: 134, top: 218, width: 720, height: 170 }, { fontSize: 58, bold: true, color: C.white });
  textBox(slide, "Kiểm soát ứng dụng, bảo vệ web và báo cáo hoạt động", { left: 138, top: 408, width: 760, height: 58 }, { fontSize: 23, color: "#D4E8E1" });
  shape(slide, "ellipse", { left: 978, top: 148, width: 164, height: 164 }, C.green, "none");
  shape(slide, "ellipse", { left: 1031, top: 201, width: 58, height: 58 }, C.navy, "none");
  textBox(slide, "03", { left: 986, top: 327, width: 150, height: 78 }, { fontSize: 58, bold: true, color: C.mint, alignment: "center" });
  textBox(slide, "12.10.2026", { left: 138, top: 582, width: 240, height: 25 }, { fontSize: 14, bold: true, color: "#9FC9BB" });
  addNotes(slide, ["Tổng hợp từ mã nguồn và tài liệu OpenGuard Kids tại mốc 12/10/2026."]);
}

// 2. Goals and delivery
{
  const slide = baseSlide(presentation, "Tuần 3 hoàn thành lõi F2 và F3", 2);
  textBox(slide, "Phạm vi tuần này chuyển hệ thống từ quản lý thời gian sang bảo vệ và báo cáo hoạt động.", { left: 54, top: 137, width: 1040, height: 38 }, { fontSize: 19, color: C.muted });
  const items = [
    ["01", "Sự kiện", "Outbox offline, chống trùng, giải thích lý do chặn"],
    ["02", "Ứng dụng", "Nhận diện SHA-256, allowlist/blocklist, popup qua Tray"],
    ["03", "Website", "DNS proxy, sáu nhóm nội dung và SafeSearch"],
    ["04", "Báo cáo", "Ngày/tuần, top ứng dụng/tên miền và xuất PDF"],
  ];
  items.forEach((item, i) => {
    const y = 205 + i * 99;
    label(slide, item[0], 60, y, i === 3 ? C.navy2 : C.green);
    textBox(slide, item[1], { left: 126, top: y - 2, width: 230, height: 32 }, { fontSize: 23, bold: true, color: C.navy });
    textBox(slide, item[2], { left: 360, top: y, width: 760, height: 34 }, { fontSize: 18, color: C.ink });
    if (i < items.length - 1) shape(slide, "rect", { left: 126, top: y + 53, width: 1000, height: 1 }, C.line, "none");
  });
  shape(slide, "roundRect", { left: 54, top: 620, width: 1170, height: 52 }, C.pale, "none", "rounded-xl");
  textBox(slide, "Kết quả: toàn bộ Definition of Done về chức năng đã có mã và kiểm thử tự động; nghiệm thu Windows thật vẫn là bước tiếp theo.", { left: 78, top: 634, width: 1120, height: 26 }, { fontSize: 16, bold: true, color: C.green });
  addNotes(slide, ["docs/WEEK3_HANDOFF.md, mục 7–8", "docs/WEEK3_EVENTS.md", "docs/F2_TESTING.md", "docs/F3_REPORTS.md"]);
}

// 3. Architecture flow
{
  const slide = baseSlide(presentation, "Luồng dữ liệu hoạt động và đồng bộ offline", 3);
  textBox(slide, "Mỗi sự kiện có UUID cố định. Agent chỉ đánh dấu đã gửi sau khi server xác nhận.", { left: 54, top: 139, width: 950, height: 34 }, { fontSize: 18, color: C.muted });
  const nodes = [
    { x: 58, title: "Windows + Tray", body: "Ứng dụng, DNS, quota\nvà yêu cầu xin giờ" },
    { x: 303, title: "Agent Service", body: "Chuẩn hóa 9 loại sự kiện\nvà giải thích tại thời điểm chặn" },
    { x: 548, title: "SQLite outbox", body: "Giữ dữ liệu khi offline\nretry nguyên UUID" },
    { x: 793, title: "FastAPI server", body: "Batch tối đa 100\nchống trùng theo thiết bị + UUID" },
    { x: 1038, title: "Dashboard", body: "Sự kiện, báo cáo\nvà trạng thái xóa" },
  ];
  nodes.forEach((node, i) => {
    shape(slide, "roundRect", { left: node.x, top: 250, width: 185, height: 166 }, i === 2 ? C.pale : C.white, i === 2 ? C.green : C.line, "rounded-xl");
    label(slide, String(i + 1), node.x + 16, 266, i === 2 ? C.navy2 : C.green);
    textBox(slide, node.title, { left: node.x + 16, top: 310, width: 153, height: 32 }, { fontSize: 18, bold: true, color: C.navy });
    textBox(slide, node.body, { left: node.x + 16, top: 350, width: 153, height: 52 }, { fontSize: 13, color: C.muted });
    if (i < nodes.length - 1) shape(slide, "rightArrow", { left: node.x + 191, top: 317, width: 48, height: 30 }, C.mint, "none");
  });
  textBox(slide, "Khi kết nối trở lại", { left: 550, top: 455, width: 183, height: 26 }, { fontSize: 15, bold: true, color: C.green, alignment: "center" });
  shape(slide, "rightArrow", { left: 548, top: 489, width: 425, height: 34 }, C.green, "none");
  textBox(slide, "Server ACK một lần, dữ liệu không nhân đôi", { left: 604, top: 533, width: 330, height: 28 }, { fontSize: 15, bold: true, color: C.navy, alignment: "center" });
  bullets(slide, ["Không ghi URL đầy đủ, query string, nội dung HTTPS hoặc tiêu đề cửa sổ.", "Tray vắng mặt hoặc chưa đăng nhập thì hệ thống không thu thập hoạt động."], { left: 96, top: 598, width: 1080, height: 74 }, { fontSize: 16, spaceAfterPoints: 5 });
  addNotes(slide, ["docs/WEEK3_EVENTS.md, mục Thiết kế sự kiện và Đồng bộ, chống trùng và xóa", "docs/PRIVACY.md"]);
}

// 4. App control
{
  const slide = baseSlide(presentation, "Kiểm soát ứng dụng dễ hiểu với phụ huynh", 4);
  textBox(slide, "SHA-256 vẫn bảo vệ việc nhận diện, nhưng dashboard không bắt phụ huynh tự tìm hoặc nhập mã.", { left: 54, top: 138, width: 1120, height: 35 }, { fontSize: 18, color: C.muted });
  bullets(slide, [
    "Agent tự phát hiện tệp thực thi và gửi tên cùng mã nhận diện.",
    "Ứng dụng phổ biến hiển thị tên thân thiện và icon đặc trưng.",
    "Tiến trình hệ thống được thu gọn. Ứng dụng đã đặt quyền luôn nằm ở danh sách chính.",
    "Tìm kiếm và bộ lọc Nổi bật, Đã thiết lập, Tất cả không làm thay đổi chính sách.",
  ], { left: 60, top: 220, width: 425, height: 300 }, { fontSize: 18, spaceAfterPoints: 14 });
  shape(slide, "roundRect", { left: 60, top: 552, width: 414, height: 78 }, "#FFF4DE", "none", "rounded-xl");
  textBox(slide, "Lưu ý", { left: 82, top: 566, width: 74, height: 22 }, { fontSize: 13, bold: true, color: "#A56A16" });
  textBox(slide, "Khi ứng dụng cập nhật thành tệp mới, mã hash thay đổi và phụ huynh cần xem lại luật.", { left: 82, top: 591, width: 365, height: 31 }, { fontSize: 14, color: "#7B571D" });
  addScreenshot(slide, SCREEN_APP, "Danh sách ứng dụng OpenGuard Kids với icon và nhóm tiến trình hệ thống thu gọn", { left: 530, top: 184, width: 662, height: 465 }, { left: 0.08, top: 0.73, right: 0.03, bottom: 0.015 });
  addNotes(slide, ["dashboard/index.html và dashboard/static/app.js tại mốc 12/10/2026", "docs/WEEK3_EVENTS.md, mục kiểm soát ứng dụng"]);
}

// 5. Web filtering
{
  const slide = baseSlide(presentation, "Bảo vệ web bằng DNS proxy và SafeSearch", 5);
  addScreenshot(slide, SCREEN_F2, "Màn hình cấu hình sáu nhóm website và SafeSearch", { left: 58, top: 166, width: 610, height: 476 }, { left: 0.02, top: 0.12, right: 0.02, bottom: 0.42 });
  textBox(slide, "Phạm vi triển khai", { left: 722, top: 168, width: 410, height: 34 }, { fontSize: 23, bold: true, color: C.navy });
  bullets(slide, [
    "Proxy UDP/TCP trên 127.0.0.1:53, áp dụng cho tên miền con.",
    "Sáu nhóm nội dung với 311 miền seed và tối đa 200 tùy chỉnh mỗi hồ sơ.",
    "Google và Bing chuyển sang endpoint SafeSearch bắt buộc.",
    "Công tắc DNS proxy cho phép bật hoặc tắt độc lập với kiểm soát ứng dụng.",
    "Service lưu cấu hình mạng cũ và khôi phục khi tắt bảo vệ hoặc dừng dịch vụ.",
  ], { left: 720, top: 220, width: 470, height: 310 }, { fontSize: 17, spaceAfterPoints: 11 });
  shape(slide, "roundRect", { left: 720, top: 556, width: 476, height: 87 }, "#FFF0EF", "none", "rounded-xl");
  textBox(slide, "Giới hạn hiện tại", { left: 744, top: 570, width: 190, height: 23 }, { fontSize: 14, bold: true, color: C.red });
  textBox(slide, "DoH/DoT, VPN, DNS cache và truy cập bằng IP trực tiếp vẫn có thể vượt bộ lọc.", { left: 744, top: 599, width: 425, height: 33 }, { fontSize: 15, color: "#8D3E41" });
  addNotes(slide, ["docs/F2_TESTING.md", "docs/WEB_PROTECTION.md"]);
}

// 6. Reports
{
  const slide = baseSlide(presentation, "Báo cáo hoạt động có cấu trúc và dễ đọc", 6);
  addScreenshot(slide, SCREEN_REPORT, "Dashboard báo cáo với KPI, biểu đồ ngày và tuần", { left: 58, top: 165, width: 750, height: 465 }, { left: 0.07, top: 0.08, right: 0.03, bottom: 0.38 });
  textBox(slide, "Nội dung báo cáo", { left: 852, top: 171, width: 320, height: 32 }, { fontSize: 23, bold: true, color: C.navy });
  bullets(slide, [
    "Biểu đồ 7 ngày có thứ trong tuần và ngày cụ thể.",
    "Xu hướng 8 tuần, top ứng dụng và top tên miền.",
    "KPI thời gian sử dụng cùng số lần bị chặn.",
    "Bộ lọc 7/28/90 ngày và xuất PDF tuần.",
    "Số liệu DNS được ghi rõ là lượt truy vấn, không phải lượt mở trang.",
  ], { left: 850, top: 223, width: 355, height: 305 }, { fontSize: 18, spaceAfterPoints: 13 });
  textBox(slide, "Dashboard và Tray dùng cùng bộ tổng hợp dữ liệu để tránh diễn giải khác nhau giữa phụ huynh và trẻ.", { left: 852, top: 555, width: 350, height: 76 }, { fontSize: 16, bold: true, color: C.green });
  addNotes(slide, ["docs/F3_REPORTS.md", "dashboard/index.html và dashboard/static/app.js tại mốc 12/10/2026"]);
}

// 7. Privacy and deletion
{
  const slide = baseSlide(presentation, "Quyền riêng tư và xóa dữ liệu theo thế hệ", 7);
  textBox(slide, "Sự kiện chỉ giữ dữ liệu cần cho giải thích, báo cáo và thực thi chính sách.", { left: 54, top: 140, width: 1000, height: 35 }, { fontSize: 18, color: C.muted });
  const stages = [
    ["1", "Yêu cầu xóa", "Server tăng generation\nvà xóa dữ liệu hiện có"],
    ["2", "Thiết bị offline", "Dashboard hiển thị\nđang chờ xác nhận"],
    ["3", "Kết nối lại", "Agent xóa history + outbox\ntrước khi upload"],
    ["4", "Hoàn tất", "Thiết bị ACK generation mới\nkhông gửi lại dữ liệu cũ"],
  ];
  stages.forEach((stage, i) => {
    const x = 62 + i * 300;
    label(slide, stage[0], x, 231, i === 3 ? C.navy2 : C.green);
    textBox(slide, stage[1], { left: x, top: 276, width: 225, height: 34 }, { fontSize: 21, bold: true, color: C.navy });
    textBox(slide, stage[2], { left: x, top: 323, width: 230, height: 65 }, { fontSize: 16, color: C.muted });
    if (i < stages.length - 1) shape(slide, "rightArrow", { left: x + 230, top: 290, width: 54, height: 28 }, C.mint, "none");
  });
  shape(slide, "rect", { left: 62, top: 431, width: 1155, height: 1 }, C.line, "none");
  textBox(slide, "Dữ liệu gửi về server", { left: 62, top: 458, width: 300, height: 32 }, { fontSize: 22, bold: true, color: C.navy });
  bullets(slide, ["Bảy trường F3 cùng UUID, generation và lời giải thích.", "Retention 90 ngày ở cả server và agent; SQLite bật secure_delete."], { left: 62, top: 506, width: 500, height: 98 }, { fontSize: 17, spaceAfterPoints: 8 });
  textBox(slide, "Không gửi về server", { left: 685, top: 458, width: 300, height: 32 }, { fontSize: 22, bold: true, color: C.navy });
  bullets(slide, ["URL/query string, nội dung HTTPS và tiêu đề cửa sổ.", "Đường dẫn tệp, PID và hash thực thi trong lịch sử sự kiện."], { left: 685, top: 506, width: 485, height: 98 }, { fontSize: 17, spaceAfterPoints: 8 });
  addNotes(slide, ["docs/WEEK3_EVENTS.md, mục Thiết kế sự kiện và Đồng bộ, chống trùng và xóa", "docs/PRIVACY.md"]);
}

// 8. Test evidence
{
  const slide = baseSlide(presentation, "Bằng chứng kiểm thử tại mốc tuần 3", 8);
  const metrics = [
    { value: "179", label: "pytest đạt", note: "Mốc 09/10/2026", color: C.green },
    { value: "108", label: "test F2/F3/Tray", note: "Mốc 11/10/2026", color: C.navy2 },
    { value: "50/50", label: "miền chặn đạt", note: "DNS isolated", color: C.green },
    { value: "20/20", label: "miền giáo dục cho phép", note: "DNS isolated", color: C.navy2 },
  ];
  metrics.forEach((m, i) => {
    const x = 62 + i * 295;
    textBox(slide, m.value, { left: x, top: 205, width: 240, height: 74 }, { fontSize: 48, bold: true, color: m.color });
    textBox(slide, m.label, { left: x, top: 286, width: 245, height: 35 }, { fontSize: 19, bold: true, color: C.navy });
    textBox(slide, m.note, { left: x, top: 329, width: 220, height: 24 }, { fontSize: 13, color: C.muted });
    if (i < metrics.length - 1) shape(slide, "rect", { left: x + 257, top: 207, width: 1, height: 144 }, C.line, "none");
  });
  shape(slide, "roundRect", { left: 62, top: 413, width: 545, height: 154 }, C.pale, "none", "rounded-xl");
  textBox(slide, "480 truy vấn DNS", { left: 91, top: 438, width: 300, height: 40 }, { fontSize: 27, bold: true, color: C.green });
  textBox(slide, "A/AAAA trên UDP và TCP, gồm hostname gốc và www.", { left: 91, top: 492, width: 470, height: 52 }, { fontSize: 16, color: C.ink });
  shape(slide, "roundRect", { left: 651, top: 413, width: 566, height: 154 }, C.white, C.line, "rounded-xl");
  textBox(slide, "Dashboard regression đạt", { left: 681, top: 438, width: 410, height: 40 }, { fontSize: 27, bold: true, color: C.navy });
  textBox(slide, "Edge headless kiểm tra đăng nhập, bộ lọc, báo cáo, PDF, responsive và chuyển hồ sơ.", { left: 681, top: 492, width: 487, height: 58 }, { fontSize: 16, color: C.ink });
  textBox(slide, "Các bài đo isolated không thay đổi DNS adapter hoặc policy thật trên máy phát triển.", { left: 62, top: 617, width: 1040, height: 30 }, { fontSize: 15, color: C.muted });
  addNotes(slide, ["docs/WEEK3_EVENTS.md, Kết quả kiểm chứng ngày 09/10/2026", "docs/F2_TESTING.md, Giới hạn còn lại", "output/f2-dns.json"]);
}

// 9. Integration fixes
{
  const slide = baseSlide(presentation, "Các vấn đề sau tích hợp đã được xử lý", 9);
  const rows = [
    ["Tray không xuất hiện sau khi khởi động", "Đăng ký startup, bảo đảm singleton và khôi phục cửa sổ đang chạy."],
    ["Ứng dụng đã chặn vẫn tiếp tục chạy", "Đường thực thi App Controller dùng policy đã đồng bộ và chỉ tác động phiên Windows của trẻ."],
    ["Biểu đồ khó đọc", "Chuyển sang biểu đồ HTML/CSS, thêm thứ trong tuần, tooltip và kích thước phù hợp."],
    ["Phụ huynh phải hiểu SHA-256", "Dashboard dùng catalog tự phát hiện, icon và nhóm tiến trình nền mở rộng."],
    ["DNS proxy thiếu quyền lựa chọn", "Thêm công tắc riêng, đồng bộ policy và khôi phục DNS khi tắt."],
  ];
  rows.forEach((row, i) => {
    const y = 174 + i * 91;
    label(slide, String(i + 1), 62, y + 3, i % 2 ? C.navy2 : C.green);
    textBox(slide, row[0], { left: 126, top: y, width: 370, height: 48 }, { fontSize: 18, bold: true, color: C.navy });
    textBox(slide, row[1], { left: 525, top: y, width: 650, height: 54 }, { fontSize: 16, color: C.ink });
    if (i < rows.length - 1) shape(slide, "rect", { left: 126, top: y + 68, width: 1050, height: 1 }, C.line, "none");
  });
  addNotes(slide, ["git log và mã nguồn tại mốc 12/10/2026", "dashboard/static/app.js", "agent/tray_ui.py", "agent/filtering.py", "agent/web_protection.py"]);
}

// 10. Handoff and next step
{
  const slide = baseSlide(presentation, "Bàn giao tuần 3 và bước tiếp theo", 10);
  textBox(slide, "Kịch bản demo đề xuất", { left: 60, top: 157, width: 430, height: 34 }, { fontSize: 24, bold: true, color: C.navy });
  const demo = [
    "Chặn một ứng dụng lab và xem popup lý do.",
    "Chặn tên miền qua DNS proxy, xác nhận SafeSearch.",
    "Mở báo cáo ngày/tuần và xuất PDF.",
    "Tắt server, tạo sự kiện rồi kết nối lại để chứng minh không nhân đôi.",
  ];
  bullets(slide, demo, { left: 62, top: 213, width: 510, height: 290 }, { fontSize: 19, spaceAfterPoints: 17 });
  shape(slide, "rect", { left: 625, top: 154, width: 1, height: 430 }, C.line, "none");
  textBox(slide, "Cần hoàn tất trước khi production", { left: 680, top: 157, width: 500, height: 34 }, { fontSize: 24, bold: true, color: C.navy });
  bullets(slide, [
    "Nghiệm thu Windows thật: service, Tray, ứng dụng, DNS adapter và khóa máy.",
    "Rà soát dataset 311 miền trước khi tuyên bố mức độ an toàn nội dung.",
    "Chống bypass bằng WFP/firewall và xử lý nhiều phiên Windows.",
    "Đóng gói cài đặt, ký mã và hoàn thiện quy trình phục hồi sự cố.",
  ], { left: 680, top: 213, width: 500, height: 290 }, { fontSize: 18, spaceAfterPoints: 15 });
  shape(slide, "roundRect", { left: 60, top: 601, width: 1128, height: 61 }, C.green, "none", "rounded-xl");
  textBox(slide, "Tuần 3 đã đủ để demo xuyên suốt F2/F3 trong môi trường lab; các giới hạn production được ghi rõ và chưa bị che giấu.", { left: 88, top: 618, width: 1070, height: 30 }, { fontSize: 17, bold: true, color: C.white, alignment: "center" });
  addNotes(slide, ["docs/WEEK3_EVENTS.md", "docs/F2_TESTING.md", "docs/F3_REPORTS.md", "docs/WEB_PROTECTION.md"]);
}

for (const [index, slide] of presentation.slides.items.entries()) {
  const png = await presentation.export({ slide, format: "png", scale: 1 });
  await fs.writeFile(path.join(RENDER, `slide-${String(index + 1).padStart(2, "0")}.png`), new Uint8Array(await png.arrayBuffer()));
}

const stagingDir = path.join(BUILD, "finalizer");
await fs.mkdir(stagingDir, { recursive: true });
const candidatePath = path.join(stagingDir, "candidate-week3.pptx");
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const result = await finalizePresentation({
  explicitTotalSlideCount: 10,
  requiredNativeTableOwnerSlides: [],
  requiredNativeChartOwnerSlides: [],
  workspaceDir: WORKSPACE,
  candidatePath,
  finalPath: FINAL,
  pythonExecutable: path.join(RUNTIME_ROOT, "python/python.exe"),
  integrityValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: ["--expected-slide-size-emu", "12192000,6858000", "--validate-bullet-geometry", "--validate-heading-fit"],
  fontPolicy: { basis: "design", families: [FONT] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "OpenGuardKids_BaoCao_Tuan3_v2.validation.json"),
});

console.log(JSON.stringify({ final: FINAL, slideCount: presentation.slides.items.length, result }, null, 2));
