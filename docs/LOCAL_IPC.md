# Giao tiếp cục bộ Service - Tray UI

Đây là giao thức phát triển phiên bản 1 giữa Windows Service và giao diện khay hệ
thống. Giao thức chỉ hoạt động trên máy cục bộ; không thay thế API giữa agent và
server.

## Ranh giới bảo mật

- Tên pipe: `\\.\pipe\OpenGuardKids.Agent.v1`.
- Pipe từ chối máy khách từ xa.
- SYSTEM, Administrators và người dùng cục bộ có quyền truy cập pipe để Tray UI của
  trẻ có thể kết nối kể cả khi chạy bằng tài khoản chuẩn. Cờ từ chối máy khách từ xa
  giữ endpoint này ở phạm vi cục bộ; service vẫn kiểm tra từng thao tác và không nhận
  lệnh đặc quyền từ UI.
- Mỗi thông điệp là một JSON UTF-8 tối đa 64 KiB. Audit trả cho Tray được giới hạn
  5 mục gần nhất; phản hồi vượt ngưỡng trả lỗi thay vì làm service dừng.
- Service kiểm tra phiên bản, kiểu dữ liệu và giới hạn giá trị trước khi xử lý.
- Không truyền token thiết bị, mật khẩu, nội dung gõ phím hoặc URL/nội dung duyệt web.
  Tuần 3 truyền tên miền tối thiểu và lời giải thích sự kiện chặn cho hồ sơ hiện tại.

## Bổ sung Tuần 3

- `get_status`/`ui_heartbeat` trả `activity_events` (30 lần chặn gần nhất),
  `blocking_notifications` (tối đa 10 mục chưa xác nhận), `filtering` (trạng thái/lỗi).
- `ack_blocking_events` nhận `event_ids` tối đa 10 UUID. Service chỉ xác nhận mục
  thuộc hồ sơ đang đăng nhập. Tray xác nhận sau khi trẻ đóng popup.
- Named pipe dùng PID thật của caller cho ui_heartbeat thay vì tin process_id
  do payload khai báo; App Controller giới hạn trong Windows session của Tray.
- Chuyển hồ sơ hoặc xóa dữ liệu làm đóng popup không còn thuộc dữ liệu hiển thị;
  popup không tự hiện lịch sử của trẻ khác. Token và cache service không đưa cho Tray.

## Envelope

Yêu cầu:

```json
{
  "protocol_version": 1,
  "request_id": "uuid",
  "type": "get_status",
  "payload": {}
}
```

Phản hồi thành công:

```json
{
  "protocol_version": 1,
  "request_id": "uuid",
  "ok": true,
  "data": {}
}
```

Phản hồi lỗi chứa `ok: false` và đối tượng `error` gồm `code`, `message`.

## Thao tác hiện có

| Type | Mục đích | Ghi chú |
|---|---|---|
| `ping` | Kiểm tra pipe và service | Dùng trong script cài đặt |
| `get_status` | Đọc trạng thái Service và F1 | Có quota, mode, grace và event đang chờ |
| `ui_heartbeat` | Báo Tray hiện diện, idle seconds và session locked | Mỗi giây; hết hạn sau 15 giây |
| `ack_time_events` | Xác nhận Tray đã hiển thị event | Tối đa 20 event ID/lần |
| `ack_lock` | Xác nhận Windows đã nhận yêu cầu khóa | Hỗ trợ quota/schedule và `remote_lock` kèm command ID; mỗi directive chỉ chạy một lần |
| `demo_reduce_time` | Trừ 1–3600 giây quota cho demo phát triển | Chỉ có trong test agent; không phải production API |
| `enroll_device` | Nhận mã ghép đôi 8 ký tự từ Tray | Service gửi tới server, lưu token trong thư mục ACL; chỉ chấp nhận trước lần ghép thành công |
| `start_session` | Nhận `username` và PIN 6 số rồi xác minh local | Không hiển thị danh sách chọn; hash được đồng bộ từ server vào cache ACL; tối đa 5 lần sai/15 phút |
| `end_session` | Kết thúc phiên trẻ đang sử dụng | Dashboard xóa tên người dùng ở heartbeat tiếp theo |
| `request_more_time` | Xếp và đánh thức luồng gửi ngay yêu cầu 1-120 phút cho phụ huynh | Bắt buộc đã đăng nhập; request chứa người gửi, phút và request ID; khi mất mạng sẽ thử lại |

`ui_heartbeat.payload` có `visible` (boolean), `idle_seconds` (0–604800) và
`session_locked` (boolean). PID chỉ phục vụ chẩn đoán và không được dùng làm bằng
chứng quyền hạn. `get_status.data.time_control` trả mode, usage/quota/remaining tính
bằng giây, schedule state, grace, lock directive và notifications. Trạng thái còn có
`enrollment.required/enrolled`; khi chưa ghép, mode là `awaiting_pairing` và F1 không
đếm cho tới khi có policy hợp lệ từ server.

## Trạng thái milestone Tuần 2

Service thực hiện phần F1 bắt buộc: quota, lịch 7×48, idle/lock-aware accounting,
cảnh báo, grace và phát hiện lùi đồng hồ. Tray thực hiện lệnh khóa trong phiên người
dùng. Khi thiếu heartbeat, trạng thái chuyển `inert_no_tray`: không đếm và không
khóa để agent không chạy ẩn. Lõi F4 đã bật: Service nhận policy đã ký và lệnh khẩn
từ server, sau đó chỉ chuyển lock directive tối thiểu cho Tray. Theo dõi ứng dụng
và DNS chưa được bật.

Service không tin các trường tùy ý ngoài schema và không cho Tray sửa policy hay
usage. PIN chỉ nhận diện hồ sơ trẻ cùng tài khoản phụ huynh trong bản demo, chưa ràng
buộc mật mã Tray với hồ sơ đó. Xác minh danh tính process gọi pipe và bảo vệ chống
giả heartbeat vẫn là việc bắt buộc trước production.

Mỗi lần script test ghi policy local, `version` tăng và reset quota allocation như
đã mô tả ở F1 test. Policy đồng bộ từ dashboard giữ `used_seconds` hôm nay: remaining
là `max(0, quota mới - usage)` cộng `extra_seconds`. Lệnh add-time cộng riêng
`extra_seconds`, không reset usage và cho phép dùng ngoài lịch; khoản cộng hết vào
ngày mới. Restart với cùng version không reset usage. State và event persistence
đều có `recorded_at` ISO 8601 UTC.
