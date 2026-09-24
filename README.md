# OpenGuard Kids

Bộ khung tuần 1 cho đồ án hỗ trợ quản lý việc sử dụng máy tính của trẻ em.
Luồng hiện có: phụ huynh đăng nhập → tạo hồ sơ trẻ → cấp mã ghép đôi → simulator
gửi heartbeat → tải và lưu chính sách → dashboard hiển thị thiết bị.

**Đây là môi trường phát triển trên máy cá nhân, chưa phải sản phẩm hoàn chỉnh.**
Agent hiện là chương trình console hiển thị rõ ràng; chưa theo dõi ứng dụng, khóa máy,
đổi DNS, chạy nền hay cài Windows Service. Chỉ dùng dữ liệu giả cho demo.

## Chạy nhanh trên Windows

Yêu cầu Python 3.11+ (đã kiểm thử với Python 3.12), PowerShell.
Chạy tất cả lệnh từ thư mục chứa README này. Không cần kích hoạt môi trường ảo.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m server.seed
.\.venv\Scripts\python.exe -m uvicorn server.app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Nếu đã có `.venv` hoặc `.env`, giữ lại và bỏ qua bước tạo/copy tương ứng.
`requirements-lock.txt` ghi lại các phiên bản đã kiểm thử; `requirements.txt`
khai báo khoảng phiên bản để cập nhật có chủ đích.

Mở [dashboard](http://127.0.0.1:8000).
Tài khoản demo mặc định trong `.env.example`:

- Email: `parent@example.test`
- Mật khẩu: `ChangeMe-ForLocalDemo123!`

Có thể đổi thông tin trong `.env` **trước lần seed đầu tiên**. Seed không đặt lại
mật khẩu của tài khoản đã tồn tại. Không commit `.env` hay thư mục `data`.

## Demo xuyên suốt

1. Đăng nhập dashboard, tạo hồ sơ bằng tên gọi giả.
2. Chọn hồ sơ, đánh dấu đồng ý và tạo mã ghép đôi (8 ký tự, 10 phút, dùng một lần).
3. Mở terminal thứ hai tại thư mục dự án:

```powershell
.\.venv\Scripts\python.exe -m agent.simulator
```

4. Nhập mã khi được hỏi. Simulator gửi heartbeat ngay, sau đó mỗi 60 giây.
5. Dashboard cập nhật trạng thái mỗi 10 giây; không nhận heartbeat trong 120 giây
   thì thiết bị hiển thị ngoại tuyến.
6. Đổi quota ngày thường/cuối tuần. Simulator nhận policy ở heartbeat tiếp theo.
   Phiên bản trên dashboard phản ánh lần agent gửi heartbeat gần nhất, nên có thể
   chậm thêm một nhịp sau khi tải policy.
7. Dừng server: simulator báo offline và giữ cache. Bật lại server: simulator thử
   kết nối ở nhịp tiếp theo. Nhấn Ctrl+C để dừng simulator.

Xem cache sau khi simulator dừng:

```powershell
.\.venv\Scripts\python.exe -m agent.simulator --show-cache
```

Simulator chỉ lưu **policy**, giữ token trong RAM. Khởi động lại cần mã mới và tạo
thiết bị demo mới. Chạy nhiều simulator thì dùng `--cache data/agent2/policy.db`.
Tính năng giữ định danh/token qua lần khởi động sẽ được bổ sung bằng DPAPI.

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

Tests tạo database tạm, không dùng database demo.
Có 15 ca unit (tính cả tham số) và 14 ca tích hợp; đây là bộ kiểm thử nền,
chưa chứng minh các tiêu chí khóa máy, DNS hoặc hiệu năng của đề bài.
Starlette hiện phát cảnh báo chuyển từ httpx sang httpx2 trong TestClient;
các ca kiểm thử vẫn chạy được với bộ phiên bản đã khóa.

## Cấu trúc

| Đường dẫn | Nội dung |
|---|---|
| `server/app` | FastAPI, SQLAlchemy, xác thực, API phụ huynh/thiết bị |
| `server/seed.py` | Tạo tài khoản demo từ biến môi trường |
| `agent` | Simulator hiển thị console và cache SQLite |
| `dashboard` | HTML/CSS/JavaScript, phục vụ cùng origin với API |
| `tests` | Kiểm thử unit và tích hợp |
| `docs` | Kiến trúc, giao thức, quyền riêng tư và bàn giao |
| `demo` | Kịch bản demo; bổ sung video ở tuần 4 |
| `data` | Database sinh khi chạy; không đưa lên Git |

API tương tác: [Swagger](http://127.0.0.1:8000/docs).
Swagger mặc định có tải thư viện giao diện từ CDN; dùng
[OpenAPI JSON](http://127.0.0.1:8000/openapi.json) khi cần kiểm tra hoàn toàn cục bộ.
Dashboard chính không dùng CDN.

## Trạng thái và giới hạn

Đã có Argon2id, cookie HttpOnly/SameSite, CSRF, kiểm tra chủ sở hữu,
khóa đăng nhập 15 phút sau 5 lần sai, rate limit trong một process,
token thiết bị băm SHA-256 và refresh rotation, policy version và audit thay đổi.

Chưa có HTTPS/pinning, chữ ký policy, AES-GCM/DPAPI, phân quyền child-view/admin,
thu hồi thiết bị qua giao diện, lịch tuần, quota thực, retention 90 ngày,
xóa dữ liệu hai phía, event queue, WebSocket, Windows Service/Tray UI và DNS.
Không mở server ra LAN/Internet ở giai đoạn này. `OGK_COOKIE_SECURE=false`
chỉ dành cho HTTP loopback; bật true khi triển khai HTTPS.

Database được tạo bằng `create_all` cho bộ khung ban đầu; chưa có migration.
Đọc [kế hoạch bàn giao](docs/HANDOFF.md) trước khi phát triển tiếp.

Tham khảo kỹ thuật: [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/),
[SQLAlchemy ORM](https://docs.sqlalchemy.org/en/20/orm/quickstart.html).
