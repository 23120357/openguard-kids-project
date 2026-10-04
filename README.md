# OpenGuard Kids

Bản phát triển tuần 2 cho đồ án hỗ trợ quản lý việc sử dụng máy tính của trẻ em.
Luồng hiện có: phụ huynh đăng nhập → tạo hồ sơ trẻ → ghép Windows agent → dashboard
đẩy quota/lịch tuần đã ký → agent áp dụng → lệnh khẩn đi qua WebSocket.

**Đây là môi trường phát triển trên máy cá nhân, chưa phải sản phẩm hoàn chỉnh.**
Agent có simulator console và một Windows Service/Tray UI thử nghiệm. Nhánh Windows
đã thực hiện F1 cục bộ: quota, lịch tuần, idle/lock, cảnh báo, grace và khóa Windows.
Nó chưa theo dõi ứng dụng hoặc đổi DNS. F1 và lõi F4 chỉ dành cho dữ liệu giả và
máy lab. Báo cáo, cách chạy và checklist nghiệm thu nằm tại
[docs/WEEK2_F4.md](docs/WEEK2_F4.md). Bàn giao và kế hoạch Tuần 3 nằm tại
[docs/WEEK3_HANDOFF.md](docs/WEEK3_HANDOFF.md).

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

## Cài Windows agent theo luồng hiện tại

Trên dashboard, tạo hồ sơ trẻ bằng tên đăng nhập và PIN 6 số, rồi tạo mã ghép đôi.
Trên máy trẻ, mở PowerShell thường tại thư mục dự án và chạy **một lệnh**:

```powershell
& .\scripts\Setup-OGKAgent.ps1
```

Chấp nhận UAC, rồi nhập mã trong cửa sổ Tray. Màn hình ghép đôi chỉ có trước lần
ghép thành công. Sau đó tab **Đăng nhập** (mở mặc định) nhận tên đăng nhập và PIN;
tab **Hôm nay** hiển thị quota và nút xin thêm giờ; tab **Chính sách** cho trẻ xem
hạn mức, lịch và nhật ký thay đổi; tab **Ứng dụng ghi nhận gì?** giải thích dữ liệu
thu thập. Yêu cầu xin giờ được gửi ngay, dashboard tự cập nhật
mà không cần tải lại trang (kiểm tra lại mỗi 10 giây nếu mất kết nối trực tiếp).
Agent nhận quota theo policy mặc định hoặc policy phụ huynh đã sửa. Nếu server nằm ở máy khác, truyền
`-ServerUrl https://ten-may-chu:8000`; HTTP qua LAN chỉ dành cho lab và cần thêm
`-AllowInsecureHttp`. Xem [hướng dẫn đầy đủ](docs/WEEK2_F4.md).

## Demo xuyên suốt

1. Đăng nhập dashboard, tạo hồ sơ bằng tên gọi giả và PIN 6 chữ số. Hồ sơ cũ có thể được bổ sung PIN ngay trên dashboard.
2. Chọn hồ sơ, đánh dấu đồng ý và tạo mã ghép đôi (8 ký tự, 10 phút, dùng một lần).
3. Mở terminal thứ hai tại thư mục dự án:

```powershell
.\.venv\Scripts\python.exe -m agent.simulator
```

4. Nhập mã khi được hỏi. Simulator gửi heartbeat ngay, sau đó mỗi 60 giây.
5. Dashboard nhận cập nhật trực tiếp và kiểm tra lại mỗi 10 giây; không nhận heartbeat trong 120 giây
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
& .\.venv-service\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\ruff.exe check .
& .\.venv\Scripts\ruff.exe format --check .
```

Tests tạo database tạm, không dùng database demo. Bộ test bao phủ
state-machine/IPC F1, policy integrity, đồng bộ F4, đăng nhập username/PIN và WebSocket command.
Khóa Windows thật, độ trễ lịch dưới 5 giây và sai số một giờ cần chạy acceptance
trên máy lab theo `docs/F1_TESTING.md`; DNS chưa được triển khai.
Starlette hiện phát cảnh báo chuyển từ httpx sang httpx2 trong TestClient;
các ca kiểm thử vẫn chạy được với bộ phiên bản đã khóa.
Kết quả tại mốc bàn giao hiện tại là **140 passed**.

## Windows Service và Tray UI thử nghiệm (demo F1 cục bộ không ghép server)

Mở PowerShell bằng **Run as administrator**, rồi chạy:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& .\scripts\Install-OGKTestService.ps1
```

Script tạo môi trường `.venv-service`, cài phụ thuộc, đăng ký service thật với tên
`OpenGuardKidsAgentTest`, đặt startup `Manual`, tạo thư mục ProgramData có ACL,
khởi động service và kiểm tra named pipe. F1 được cài ở trạng thái tắt an toàn. Nếu
Python không được tự động tìm thấy, truyền đường dẫn Python 3.11+ bằng
`-PythonExecutable`. Installer từ chối Microsoft Store `WindowsApps` alias vì
LocalSystem không thể dùng alias này để khởi động Service.

> **Chỉ dùng trong máy lab:** service thử nghiệm chạy dưới LocalSystem trực tiếp từ
> thư mục mã nguồn và chưa phải gói cài đặt được khóa ACL cho production. Luôn chạy
> script cleanup sau khi thử; không để service này trên máy dùng hằng ngày.

Vẫn trong PowerShell quản trị, bật policy lab:

```powershell
& .\scripts\Set-OGKF1TestPolicy.ps1
```

Lệnh này bật policy F1 local 3 phút cho demo offline. Nếu dùng policy dashboard,
hãy dùng lệnh cài đặt một bước và màn hình ghép đôi trong Tray theo
[hướng dẫn Tuần 2](docs/WEEK2_F4.md); script local sẽ từ chối ghi đè policy đã ghép.
Quay lại PowerShell thường để chạy Tray:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& .\scripts\Start-OGKTray.ps1 -Open
```

Lệnh start có tính singleton: lần đầu tạo một Tray icon và một cửa sổ; các lần sau
chỉ gửi tín hiệu mở cửa sổ đang có. Mutex toàn máy chặn cả trường hợp hai lệnh start
chạy đồng thời. Sau khi nâng cấp từ bản chưa có singleton, thoát Tray cũ đúng một
lần rồi chạy lại script.

Kết thúc thử nghiệm bằng PowerShell quản trị:

```powershell
& .\scripts\Cleanup-OGKTestService.ps1
```

Thêm `-RemoveRuntime` để xóa `.venv-service`, và `-RemoveAgentData` để xóa vĩnh viễn
policy/usage/event F1. Script cleanup chỉ nhắm đúng service và thư mục thử nghiệm
nêu trên. Chi tiết giao thức ở [docs/LOCAL_IPC.md](docs/LOCAL_IPC.md); quy trình
nghiệm thu F1 ở [docs/F1_TESTING.md](docs/F1_TESTING.md).

Để reset database server nhưng giữ `.venv`, dừng Uvicorn bằng `Ctrl+C`, sau đó chạy:

```powershell
Remove-Item -LiteralPath .\data\server.db -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath .\data\server.db-wal -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath .\data\server.db-shm -Force -ErrorAction SilentlyContinue
& .\.venv\Scripts\python.exe -m server.seed
```

Thao tác này xóa vĩnh viễn toàn bộ dữ liệu demo phía server. Quy trình cleanup đầy
đủ hai phía nằm tại [tài liệu bàn giao Tuần 3](docs/WEEK3_HANDOFF.md#5-cleanup).

## Cấu trúc

| Đường dẫn | Nội dung |
|---|---|
| `server/app` | FastAPI, SQLAlchemy, xác thực, API phụ huynh/thiết bị |
| `server/seed.py` | Tạo tài khoản demo từ biến môi trường |
| `agent` | Simulator, Windows Service thử nghiệm, Tray UI và cache SQLite |
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

Đã có HMAC policy, WebSocket lệnh khẩn, heartbeat fallback, audit child-view và
policy F1 từ server, username/PIN do phụ huynh tạo cho từng hồ sơ và Tray nhập để đăng nhập,
dashboard hiển thị người dùng máy,
request xin giờ có duyệt/từ chối và cộng allowance trong ngày. Chưa có
HTTPS/pinning, chữ ký bất đối xứng, AES-GCM/DPAPI,
phân quyền admin hoàn chỉnh, thu hồi thiết bị qua giao diện, xóa dữ liệu hai phía,
event batch hay DNS. Agent chưa chống bypass và chưa xử lý multi-session nên chưa
phải production agent.
Chỉ mở server ra LAN trong mạng lab tin cậy; không mở ra Internet ở giai đoạn này. `OGK_COOKIE_SECURE=false`
chỉ dành cho HTTP loopback; bật true khi triển khai HTTPS.

Database được tạo bằng `create_all` cho bộ khung ban đầu; chưa có migration.
Đọc [kế hoạch bàn giao](docs/HANDOFF.md) trước khi phát triển tiếp.

## Tài liệu hiện hành

- [Kiến trúc đang chạy](docs/ARCHITECTURE.md)
- [Báo cáo và nghiệm thu Tuần 2](docs/WEEK2_F4.md)
- [Bàn giao và kế hoạch Tuần 3](docs/WEEK3_HANDOFF.md)
- [Kiểm thử F1 trên Windows](docs/F1_TESTING.md)
- [Hợp đồng agent/server](docs/AGENT_SERVER_API.md)
- [Giao thức named pipe](docs/LOCAL_IPC.md)
- [Dữ liệu và quyền riêng tư](docs/PRIVACY.md)

Tham khảo kỹ thuật: [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/),
[SQLAlchemy ORM](https://docs.sqlalchemy.org/en/20/orm/quickstart.html).
