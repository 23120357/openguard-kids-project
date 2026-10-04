# API đang triển khai - cuối Tuần 2

Base URL development: `http://127.0.0.1:8000/api`. OpenAPI runtime nằm tại
`/openapi.json`. Hợp đồng production đích chi tiết hơn nằm tại
[AGENT_SERVER_API.md](AGENT_SERVER_API.md); không coi endpoint thiết kế là đã có
nếu không xuất hiện trong OpenAPI runtime.

## Xác thực phụ huynh

- `POST /auth/login`: email/password; đặt cookie `ogk_session` HttpOnly,
  SameSite=Lax, hạn 12 giờ và trả CSRF token.
- `GET /auth/me`: trả identity và CSRF token của phiên hiện hành.
- `POST /auth/logout`: yêu cầu CSRF; hủy session server và cookie.
- Mọi thao tác ghi của phụ huynh gửi `X-CSRF-Token`.
- Query tài nguyên luôn ràng buộc `parent_id`; tài nguyên của phụ huynh khác trả 404.

## API phụ huynh và dashboard

| Method | Path | Chức năng |
|---|---|---|
| GET/POST | `/children` | Liệt kê hoặc tạo hồ sơ với username và PIN 6 số; tạo policy mặc định |
| PUT | `/children/{id}/pin` | Đổi/bổ sung PIN và ghi audit |
| POST | `/enrollment-codes` | Mã 8 ký tự, hạn 10 phút, dùng một lần; yêu cầu consent |
| GET/PUT | `/children/{id}/policy` | Đọc hoặc cập nhật quota, enabled và lịch 7×48 bằng `expected_version` |
| GET | `/devices` | Trạng thái online, phiên trẻ, policy version, used/remaining |
| POST | `/devices/{id}/commands` | Tạo `lock_now` hoặc `add_time` và thử gửi realtime |
| GET | `/time-requests` | Danh sách request xin thêm giờ |
| POST | `/time-requests/{id}/decision` | Duyệt/từ chối; duyệt tạo command cộng giờ |
| GET | `/audit` | Tối đa 100 thay đổi mới nhất thuộc phụ huynh |
| GET | `/parent/events` | SSE báo dashboard tải lại children/policy/status |

Dashboard không dựa hoàn toàn vào SSE; polling 10 giây là fallback. Lịch UI dùng
giờ 24h và bước 30 phút, nhưng payload policy vẫn là 7 chuỗi 48 ký tự `0/1`.

## Enrollment và token thiết bị

`POST /enroll` nhận mã, tên thiết bị và fingerprint logic của lần cài đặt. Server
không thu serial phần cứng. Thành công trả device ID, child ban đầu, access token,
refresh token và khóa HMAC riêng của device. Token thô chỉ xuất hiện trong response;
server lưu SHA-256 hash.

`POST /auth/device/refresh` xoay cả access và refresh token. Access token hạn 15
phút; refresh token hạn 30 ngày. Các endpoint thiết bị dùng
`Authorization: Bearer <access_token>`.

## Đồng bộ thiết bị

| Method | Path | Chức năng |
|---|---|---|
| POST | `/heartbeat` | Gửi policy version/usage; nhận version mới và command chưa ACK |
| POST | `/device/session` | Báo child/username đang dùng máy và thời điểm bắt đầu |
| POST | `/device/time-status` | Báo used, remaining, mode và trạng thái active khoảng 3 giây/lần |
| GET | `/device/profiles` | Danh sách profile/PIN hash/policy đã ký thuộc parent của device |
| POST | `/device/requests` | Tạo request xin thêm giờ từ child đang đăng nhập |
| GET | `/policy` | Policy của child gốc của device; giữ cho compatibility |
| GET | `/device/audit` | Audit scope theo child đang hoạt động trên device |
| WS | `/device/ws` | `policy_changed`, command khẩn và ACK command |

Policy/profile document có `integrity.algorithm = hmac-sha256` và `signature` trên
JSON canonical. Agent phải giữ cache hợp lệ cũ nếu tài liệu mới sai chữ ký.

## Realtime và fallback

- Khi parent sửa policy, WebSocket gửi tín hiệu để agent tải document mới ngay.
- Command được ghi DB trước khi thử WebSocket. Nếu agent offline, heartbeat/reconnect
  trả command chưa ACK.
- Command ID ngăn cộng giờ hoặc khóa lặp khi server gửi lại.
- Request xin giờ dùng worker riêng, không chờ policy heartbeat.
- Time status dùng vòng lặp riêng để dashboard đếm đồng bộ với client.

## Audit và thời gian

Audit policy/command/request lưu actor, Unix UTC timestamp, IP trực tiếp và old/new
value. UI chuyển timestamp sang múi giờ máy người xem. Event F1 cục bộ còn có
`recorded_at` ISO 8601 UTC để chẩn đoán.

## Giới hạn hiện tại

- HTTP loopback/LAN lab, chưa có TLS/pinning.
- WebSocket development truyền access token trong query string.
- Chưa có API event batch F2/F3, retention 90 ngày hoặc xóa dữ liệu phân tán.
- Chưa có revoke device UI, household nhiều phụ huynh hoặc role admin production.
- `create_all` và migration idempotent chỉ phù hợp development; chưa có Alembic.

Test contract nằm trong `tests/test_f4_remote.py`, `tests/test_agent_setup_flow.py`
và `tests/test_realtime_updates.py`. Cách chạy đầu-cuối nằm tại
[WEEK3_HANDOFF.md](WEEK3_HANDOFF.md).
