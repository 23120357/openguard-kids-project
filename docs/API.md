# Giao thức API phiên bản 0.1

Base URL phát triển: http://127.0.0.1:8000/api.
Payload JSON; schema máy đọc được tại /openapi.json.
Lỗi có trường detail; không gửi mật khẩu/token vào log hoặc URL.

## API phụ huynh

Đăng nhập POST /auth/login với email, password.
Phản hồi có email và csrf_token, đồng thời đặt cookie ogk_session:
HttpOnly, SameSite=Lax, hạn 12 giờ. Secure bật qua OGK_COOKIE_SECURE khi dùng HTTPS.
GET /auth/me lấy email và csrf_token sau khi tải lại trang.
Mọi thao tác ghi của phụ huynh sau đăng nhập phải gửi X-CSRF-Token.
POST /auth/logout hủy session server và cookie.

| Method | Đường dẫn | Body hoặc kết quả |
|---|---|---|
| GET | /children | Danh sách hồ sơ của phụ huynh |
| POST | /children | display_name; trả id và display_name |
| POST | /enrollment-codes | child_id, consent: true; trả code, expires_at |
| GET | /children/{id}/policy | Policy hiện tại |
| PUT | /children/{id}/policy | expected_version, weekday_minutes, weekend_minutes |
| GET | /devices | id, child_id, display_name, last_seen, policy_version, online |
| GET | /audit | Tối đa 100 bản ghi mới nhất của phụ huynh |

Policy quota phải từ 1 đến 1440 phút. Version không khớp trả 409;
client cần tải lại policy trước khi chỉnh tiếp. Tài nguyên của phụ huynh khác trả 404.
Consent được ghi trong audit khi cấp mã ghép đôi.

## API thiết bị

POST /enroll:

```json
{
  "code": "ABCDEFGH",
  "display_name": "Lab device",
  "fingerprint": "random-installation-identifier"
}
```

Fingerprint mẫu là ID cài đặt ngẫu nhiên; không thu serial phần cứng.
Mã sai/hết hạn/đã dùng trả 400. Thành công trả 201:

```json
{
  "device_id": "<uuid>",
  "access_token": "<opaque-secret>",
  "refresh_token": "<opaque-secret>",
  "token_type": "bearer",
  "expires_in": 900
}
```

POST /auth/device/refresh nhận device_id và refresh_token, trả cặp token mới.
Refresh hạn 30 ngày, xoay vòng sau mỗi lần dùng; token cũ mất hiệu lực.

POST /heartbeat cần Authorization: Bearer <access_token>:

```json
{"policy_version": 0}
```

Phản hồi có server_time, policy_version, commands: [].
Chưa gửi quota đã dùng hoặc trạng thái enforcement trong bản mẫu.
GET /policy dùng cùng Bearer token, trả child_id, version, weekday_minutes,
weekend_minutes. Policy gắn với thiết bị đã xác thực, không nhận child_id tùy ý.
Token hết hạn/sai/thiết bị revoked trả 401.
Chưa triển khai command queue hay WebSocket; commands luôn là mảng rỗng.

## Giới hạn giai đoạn này

Chưa có phân trang, thu hồi thiết bị qua API, events, reports, lịch tuần,
chữ ký policy và child-view/admin. Khi thêm event phải giữ đúng 7 trường đề bài;
idempotency key nên đặt trong envelope của batch hoặc metadata vận chuyển,
không tự ý thêm nội dung nhạy cảm vào subject.
