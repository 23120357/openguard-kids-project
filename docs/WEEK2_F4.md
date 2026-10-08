# Báo cáo triển khai Tuần 2 — F1 và lõi F4

Tài liệu này mô tả đúng trạng thái mã nguồn tại mốc Tuần 2, cách chạy trên máy
Windows lab và cách kiểm chứng từng tiêu chí. Phạm vi được đối chiếu với F4 và
bảng “Kế hoạch 04 tuần” trong `QuanLyMayTinhTreEm.pdf`.

## 1. Kết quả đạt được

Sản phẩm cuối tuần 2 yêu cầu: quota và lịch tuần hoạt động; khóa máy đúng hạn; đẩy
chính sách từ dashboard xuống agent. Bảng dưới phân biệt phần đã có trong mã với
phần còn cần nghiệm thu trên Windows thật:

| Hạng mục | Trạng thái | Bằng chứng trong hệ thống |
|---|---|---|
| Mô hình 1 phụ huynh : n trẻ : m thiết bị | Đã triển khai | `Parent -> Child -> Device`; mỗi trẻ có một policy hiện hành |
| Quota ngày thường/cuối tuần | Đã triển khai + test | Dashboard sửa quota; F1 đếm active time và lưu SQLite |
| Lịch tuần | Đã triển khai + test | 7 ngày × 48 slot; UI 24h, phút `00/30`, validation tô đỏ giờ sai |
| Policy có version | Đã triển khai + test | Optimistic concurrency bằng `expected_version`; mỗi lần lưu tăng version |
| Toàn vẹn policy | Đã triển khai mức development | HMAC-SHA256; agent từ chối cache/policy bị sửa |
| Dashboard → agent trong 60 giây | Đã triển khai; cần đo đầu-cuối | WebSocket báo policy mới; heartbeat 30 giây là dự phòng |
| “Khóa ngay” trong 5 giây | Đã test kênh; cần acceptance thật | WebSocket đẩy lệnh; Tray gọi `LockWorkStation` |
| “Cộng giờ” trong 5 giây | Đã triển khai + test | Khoản cộng 1–120 phút, idempotent, không reset usage |
| Dự phòng khi WebSocket gián đoạn | Đã triển khai + test | Command lưu DB và trả lại qua heartbeat/reconnect |
| Audit ai/lúc nào/IP/giá trị cũ-mới | Đã triển khai + test | Policy và lệnh khẩn ghi audit; parent/child view theo scope |
| Trẻ xem audit (NT5) | Đã triển khai mức development | Tray hiển thị 5 thay đổi gần nhất ở tab Chính sách |
| Phiên người dùng | Đã triển khai mức demo | Username/PIN riêng; dashboard hiện ai đang dùng |
| Yêu cầu thêm giờ | Đã triển khai + test | Gửi ngay; dashboard duyệt/từ chối; Tray hiển thị kết quả |
| Agent chạy offline với policy cache | Đã triển khai + test | Policy hợp lệ được cache; F1 tiếp tục khi server tắt |

F1 từ mốc trước vẫn giữ nguyên: quota, lịch 7×48, bỏ thời gian idle/khóa màn hình,
cảnh báo 10/5/1 phút, grace period, phát hiện lùi đồng hồ, persistence có ngày giờ,
digital clock và khóa lại sau khi mở khóa nếu quota/lịch vẫn không cho phép.

## 2. Luồng hoạt động

1. Phụ huynh đăng nhập, tạo từng hồ sơ trẻ cùng PIN 6 chữ số, rồi sinh mã ghép đôi dùng một lần.
2. Tray chuyển mã qua named pipe cho service; service tạo logical device ID và lưu
   token cùng khóa ký riêng trong thư mục ACL-restricted dưới `%ProgramData%\OpenGuardKids`.
3. Service gửi heartbeat và giữ WebSocket. Danh sách hồ sơ cùng policy đã ký được
   xác thực HMAC rồi cache ở `profiles-cache.json`; mỗi hồ sơ có state SQLite riêng.
4. Policy mới được báo qua WebSocket để agent tải ngay; tổng usage hôm nay vẫn giữ.
   Remaining là `max(0, quota_mới - usage_hôm_nay)`. Khoản cộng thêm cũ không đi
   theo policy mới. Script demo F1 cục bộ là ngoại lệ: nó chủ động reset về toàn bộ quota.
5. `add_time` tăng khoản cộng riêng hôm nay đúng một lần; không đặt lại đồng hồ,
   không bị quota/lịch chặn và tự hết khi sang ngày mới. Phút đã dùng từ khoản cộng
   vẫn tính vào tổng usage; nếu policy chưa đổi, khoản cộng còn lại sống qua restart.
6. Lệnh `lock_now` đi service → named pipe → Tray trong user session. Tray gọi API
   Windows để khóa phiên rồi trả ACK. Lệnh cộng giờ được áp dụng trực tiếp và ACK
   cùng command ID, nên lệnh gửi lại không cộng lần hai.
7. Mọi thay đổi từ phụ huynh được ghi `Audit` với actor, UTC timestamp, IP,
   old/new value. Tray chỉ đọc audit của hồ sơ đang hoạt động.
8. Trẻ nhập username rồi PIN. Server giữ Argon2 hash do phụ huynh tạo, gửi hash
   qua API device được xác thực tới service để kiểm tra PIN cục bộ; PIN trẻ nhập ở
   Tray không gửi lên server. Request xin giờ gắn hồ sơ, thiết bị và số phút.

## 3. Giới hạn có chủ đích của mốc Tuần 2

- HMAC dùng shared development key. Production nên dùng chữ ký bất đối xứng,
  HTTPS/WSS, certificate pinning, DPAPI cho token và quy trình xoay khóa.
- Token/config hiện nằm trong thư mục chỉ SYSTEM/Administrators truy cập nhưng chưa
  bọc DPAPI; chỉ dùng máy lab.
- WebSocket dùng access token trong query string ở bản loopback. Không triển khai
  kiểu này trên Internet; production phải dùng WSS và cơ chế xác thực không lộ URL.
- UI lịch tuần hỗ trợ nhiều khoảng mỗi ngày và giữ nguyên đủ 48 slot khi đọc/lưu.
- Một thiết bị đã ghép có thể chọn các hồ sơ trẻ thuộc cùng tài khoản phụ huynh.
  Mô hình household nhiều phụ huynh và phân quyền giữa phụ huynh chưa triển khai.
- Đây là cách cấp PIN của bản development: server giữ hash để đồng bộ cho các máy
  cùng tài khoản. Thiết kế household đích yêu cầu binding từng thiết bị, cấp PIN
  cục bộ và lưu bộ đếm sai PIN bền vững; phần đó chưa triển khai.
- Hồ sơ được tạo trước tính năng PIN không hiện trên Tray cho tới khi phụ huynh
  đặt PIN bằng mục “Đổi hoặc bổ sung PIN” trên dashboard.
- Agent chưa ghép với dashboard giữ hồ sơ “Bản demo cục bộ” để chạy F1 offline;
  PIN/request phụ huynh chỉ có hiệu lực sau khi ghép thiết bị. Tray sẽ khóa nút xin
  giờ trong chế độ local để không tạo kỳ vọng rằng request đã tới phụ huynh.
- Sai PIN 5 lần sẽ khóa thử lại trong 15 phút. Nút Đổi hồ sơ giữ chính sách và
  bộ đếm hiện tại cho tới khi xác thực thành công hồ sơ mới. IPC từ chối kết thúc
  phiên đã đăng nhập; phiên chưa đăng nhập sau khi khởi động vẫn cần xử lý chống bypass.
- Chưa làm quy trình gỡ cài đặt bằng mật khẩu phụ huynh (mục “NÊN CÓ”).
- Chưa làm chế độ “tạm nghỉ phụ huynh 2 giờ” (mục “CÓ THÌ TỐT”).
- Chưa có migration framework; hàm migration idempotent hiện chỉ nâng database
  development từ schema Tuần 1.

## 4. Cách cài và chạy từ đầu

Chạy các lệnh tại thư mục gốc repository. Các khối dưới đây là lệnh PowerShell
trực tiếp; không gõ thêm từ `powershell` ở đầu lệnh.

### 4.1 Server và dashboard

Trong PowerShell thường:

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r .\requirements-lock.txt
if (-not (Test-Path .\.env)) { Copy-Item .\.env.example .\.env }
& .\.venv\Scripts\python.exe -m server.seed
& .\.venv\Scripts\python.exe -m uvicorn server.app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Giữ cửa sổ này mở và truy cập `http://127.0.0.1:8000`. Tài khoản demo mặc định:

- email: `parent@example.test`
- mật khẩu: `ChangeMe-ForLocalDemo123!`

Nếu `.env` dùng `OGK_POLICY_SIGNING_KEY` riêng, giữ giá trị dài ít nhất 32 ký tự.
Agent mới nhận một khóa xác thực chính sách riêng khi ghép đôi; không cần sao chép `.env` của server sang máy trẻ.

### 4.2 Cài đặt client bằng một lệnh, rồi ghép đôi trên giao diện

Trên dashboard: tạo hồ sơ trẻ với **tên đăng nhập** và PIN 6 số. Mỗi hồ sơ mới tự
có chính sách mặc định (90 phút ngày thường, 120 phút cuối tuần, bật F1). Phụ huynh
có thể sửa chính sách trước hoặc sau khi ghép. Chọn hồ sơ, đồng ý và tạo mã ghép đôi
8 ký tự.

Trên máy trẻ, trong PowerShell của **người dùng đang đăng nhập** ở thư mục dự án:

```powershell
& .\scripts\Setup-OGKAgent.ps1
```

Chấp nhận hộp thoại UAC. Lệnh này tự cài runtime/phụ thuộc nếu cần, đăng ký và bật
Windows service, kiểm tra named pipe, rồi mở đúng một Tray UI trong phiên người dùng.
Nếu server nằm ở máy khác, dùng HTTPS:

```powershell
& .\scripts\Setup-OGKAgent.ps1 -ServerUrl https://server.example.test:8000
```

Chỉ trong mạng lab tin cậy, có thể dùng HTTP rõ ràng:

```powershell
& .\scripts\Setup-OGKAgent.ps1 -ServerUrl http://192.168.1.10:8000 -AllowInsecureHttp
```

Trong Tray, nhập mã ghép đôi. Sau khi ghép thành công, màn hình này biến mất và
không hiện lại ở lần mở ứng dụng sau. Nhập tên đăng nhập của trẻ (không có danh sách
chọn) và PIN do phụ huynh tạo. Khi profile/policy đồng bộ, đồng hồ hiển thị quota
theo chính sách đang có. Nếu server chưa đồng bộ, Tray hiện trạng thái đang chờ hồ
sơ; không tự cấp quota cục bộ. Ghép đôi chỉ cần một lần; chạy lại lệnh setup không
tạo service, Tray icon hoặc cửa sổ thứ hai.

Nếu dashboard đã ghi nhận thiết bị nhưng cửa sổ Tray của bản chạy cũ vẫn ở màn
ghép đôi, mở lại **chỉ giao diện** bằng `& .\scripts\Start-OGKTray.ps1 -Restart -Open`.
Không tạo mã mới hoặc xóa dữ liệu agent. Có thể xem lỗi giao diện tại
`%LOCALAPPDATA%\OpenGuardKids\tray.log` (đường dẫn này dùng cú pháp biến môi trường
Windows; trong PowerShell tương ứng là `$env:LOCALAPPDATA\OpenGuardKids\tray.log`).

Đây là **script cài đặt cho giai đoạn phát triển**, chưa phải bộ cài EXE/MSI được
đóng gói và ký số. Windows service vẫn chạy từ thư mục source; không xóa/di chuyển
thư mục này sau khi cài. Kết nối HTTP không mã hóa chỉ dành cho lab.

Mỗi thời điểm chỉ có một service, một Tray icon, một cửa sổ và một hồ sơ đang dùng;
mỗi hồ sơ giữ policy riêng. Nếu chạy lại lệnh mở Tray, cửa sổ cũ được đưa lên trước.

Nếu thiết bị đã ghép ở phiên bản cũ, không cần ghép lại: dừng server cũ bằng
Ctrl+C rồi chạy lại lệnh `uvicorn` ở mục 4.1; trên dashboard bổ sung PIN cho từng
hồ sơ cũ; trong PowerShell quản trị chạy `Restart-Service OpenGuardKidsAgentTest`.
Trong tối đa một nhịp đồng bộ, Tray sẽ nhận danh sách hồ sơ. Nếu agent báo 404 ở
`/api/device/profiles`, server cũ vẫn đang chạy ở cổng 8000.

Nếu service đã được cài từ phiên bản trước, cập nhật dependency rồi restart thay
vì chạy installer lần nữa:

```powershell
Stop-Service OpenGuardKidsAgentTest
& .\.venv-service\Scripts\python.exe -m pip install -r .\requirements-lock.txt
Start-Service OpenGuardKidsAgentTest
```

## 5. Cách verify thủ công

### 5.1 Kiểm tra service và kết nối

Trong PowerShell quản trị:

```powershell
Get-Service OpenGuardKidsAgentTest
& .\.venv-service\Scripts\python.exe -m agent.windows_service ping
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Kỳ vọng: service là `Running`, named-pipe trả `pong`, health trả `status = ok`.
Trên dashboard, device chuyển thành “Trực tuyến” trong tối đa 30 giây. Trong Tray,
tab quyền riêng tư ghi “Máy chủ phụ huynh: đã kết nối”.

### 5.2 Policy dashboard → agent (SLA 60 giây)

1. Mở Tray và ghi lại version cùng đồng hồ hiện tại.
2. Trên dashboard, đặt quota ngày thường/cuối tuần thành 3 phút; bật kiểm soát;
   bảo đảm khoảng giờ hôm nay chứa thời điểm hiện tại; bấm **Lưu chính sách**.
3. Bắt đầu bấm giờ ngay khi dashboard báo đã lưu.
4. Khi WebSocket đang kết nối, policy được tải ngay; nếu kênh này đứt, heartbeat
   tối đa 30 giây là dự phòng. Remaining bằng quota mới trừ **tổng** usage đã có;
   audit có old/new value. Tab **Chính sách** trên Tray hiển thị quota, lịch và audit.
5. Nếu usage hôm nay lớn hơn quota mới, đồng hồ về `00:00:00`. Nếu nhỏ hơn thì
   đồng hồ hiển thị `quota mới - usage`, không cấp lại cả quota.
6. Cộng 15 phút, dùng một phần, rồi đổi quota: phút cộng cũ bị loại khỏi phép tính
   policy mới, nhưng phần thời gian đã dùng vẫn được giữ. Trong **Thiết bị đã kết nối**,
   dashboard hiện **Đã dùng hôm nay** và **Còn lại hôm nay**; số còn lại tự đếm mỗi giây,
   được agent hiệu chỉnh khoảng 3 giây/lần.
7. Trình sửa lịch dùng giờ 24h, phút chỉ có `00/30`. Giờ kết thúc `00:00` nghĩa là
   hết ngày; `23:30` chỉ kết thúc lúc 23:30. Giờ kết thúc không sau giờ bắt đầu phải
   hiện thông báo đỏ, highlight đúng ngày và không gửi policy. Tab **Chính sách**
   trên Tray hiển thị cùng khoảng thời gian từ policy đã ký.

Nếu dashboard báo server đang chạy bản cũ hoặc agent chưa gửi số liệu, cần khởi động
lại tiến trình server rồi chạy lại `& .\scripts\Setup-OGKAgent.ps1` để restart service
và Tray. Tải lại trang bằng `Ctrl+F5` sau đó; cập nhật file tĩnh không tự khởi động
lại mã Python của server.

### 5.3 Quota/lịch và khóa đúng hạn

1. Dùng nút developer trên Tray để giảm thời gian còn lại.
2. Khi quota hết, chờ grace 60 giây. Kỳ vọng Windows khóa; mở khóa lại khi chưa có giờ phải bị khóa tiếp.
3. Trên dashboard đổi lịch hôm nay để thời điểm hiện tại nằm ngoài khoảng cho
   phép. Trong tối đa 30 giây, Tray hiển thị ngoài lịch và yêu cầu khóa; mở khóa lại vẫn bị khóa tiếp.
4. Đổi sang policy/version mới để mở lại một episode thử nghiệm mới.

### 5.4 Lệnh khẩn dưới 5 giây

**Cảnh báo: bước này khóa phiên Windows thật; lưu công việc trước.**

1. Để server, service và Tray cùng chạy; nhìn trạng thái agent trực tuyến.
2. Trên dashboard bấm **Khóa ngay** và bấm giờ.
3. Kỳ vọng Windows nhận yêu cầu khóa trong dưới 5 giây; audit sau đó xuất hiện
   cả “đã gửi lệnh” và “agent đã xác nhận lệnh”.
4. Đăng nhập lại bằng PIN. Trên dashboard cộng 15 phút; Tray phải tăng đúng 15
   phút trong dưới 5 giây, usage không đổi. Thử cả khi quota hết hoặc ngoài lịch.
5. Refresh/reconnect không được cộng lần hai vì command ID đã được xử lý.

### 5.5 Đăng nhập phiên và request xin giờ

1. Mở Tray: mặc định là tab **Đăng nhập**. Nhập tên đăng nhập của trẻ, PIN do phụ huynh tạo và chọn **Đăng nhập**. PIN
   trẻ nhập không gửi lên server; sai 5 lần sẽ khóa thử lại trong 15 phút. Thử
   chuyển sang trẻ khác: chọn Đổi hồ sơ rồi nhập tên đăng nhập và PIN mới; mỗi trẻ
   giữ usage và quota riêng.
2. Tab **Đăng nhập** đổi thành **Đã đăng nhập với tư cách [username]** và có nút
   **Đổi hồ sơ**; tab **Hôm nay** hiển thị đồng hồ riêng. Dashboard → Thiết bị
   đã kết nối hiện **Đang dùng: [tên hồ sơ]** và thời điểm bắt đầu. Bấm **Đổi hồ sơ**
   để trở lại biểu mẫu đăng nhập; chính sách hiện tại vẫn áp dụng trong lúc đổi.
3. Trong tab **Hôm nay**, cuộn bằng bánh xe chuột để xem các phần bên dưới. Đổi số phút
   ở ô nhập (mặc định 15), sau đó bấm **Xin thêm giờ**.
4. Giữ dashboard đang mở ở trình duyệt. **Yêu cầu xin thêm giờ** phải tự hiện trong
   vài giây, không cần tải lại trang và không đợi heartbeat kế tiếp; thông tin gồm
   giờ gửi, người gửi, số phút, tên máy và trạng thái, ví dụ
   `16:01:08 4/10/2026 · labubu xin 18 phút · Máy Laptop học tập · Đã duyệt`.
   Chọn **Duyệt và cộng giờ**
   hoặc **Từ chối**. Nếu mất kết nối sự kiện trực tiếp, dashboard tự kiểm tra lại mỗi 10 giây.
5. Sau khi agent thực sự áp dụng lệnh duyệt, ngay dưới nút **Xin thêm giờ** trên Tray
   hiện **Đã cộng thêm X phút.** Nếu phụ huynh từ chối, hiện **Yêu cầu xin thêm X phút
   đã bị từ chối.** Dashboard và audit phía trẻ ghi nhận quyết định. Khi mất kênh
   trực tiếp, quyết định từ chối được nhận ở lần đồng bộ audit kế tiếp.

### 5.6 Từ chối policy cache bị sửa

Để quan sát fail-safe rõ ràng, trước tiên dừng server, rồi trong PowerShell quản
trị dừng service và sửa một giá trị trong
`$env:ProgramData\OpenGuardKids\remote-policy.json` mà không cập nhật signature:

```powershell
Stop-Service OpenGuardKidsAgentTest
notepad "$env:ProgramData\OpenGuardKids\remote-policy.json"
Start-Service OpenGuardKidsAgentTest
```

Kỳ vọng: service vẫn chạy nhưng F1 ở trạng thái tắt an toàn và Tray báo policy có
lỗi; policy đã sửa không được áp dụng. Khởi động lại server: agent tải policy hợp
lệ ở heartbeat kế tiếp và tự phục hồi. Không dùng bài test này trên máy hằng ngày.

### 5.7 Audit phía trẻ

Mở Tray → **Chính sách**. Kỳ vọng thấy chính sách hiện hành và tối đa 5 thay đổi gần
nhất của phụ huynh. API nội bộ trả actor, timestamp, IP và old/new values; không trả audit
của trẻ khác vì truy vấn bị ràng buộc bằng child ID của device token.

## 6. Kiểm thử tự động

```powershell
& .\.venv-service\Scripts\python.exe -m pytest -q
& .\.venv-service\Scripts\python.exe -m ruff check .
& .\.venv-service\Scripts\python.exe -m ruff format --check .
```

Bộ test hiện tại đạt **140 passed**. Checklist trên vẫn cần nghiệm thu thủ công
trên máy lab, đặc biệt lệnh khóa Windows thật, sai số một giờ và đo latency policy.

## 7. Cleanup

Xóa service nhưng **giữ nguyên các Python package** trong `.venv-service`:

```powershell
& .\scripts\Cleanup-OGKTestService.ps1
```

Xóa thêm policy, token enrollment, cache và usage của agent:

```powershell
& .\scripts\Cleanup-OGKTestService.ps1 -RemoveAgentData
```

Chỉ thêm `-RemoveRuntime` khi muốn xóa cả `.venv-service` và toàn bộ package đã cài.

Để reset server nhưng giữ package Python, nhấn `Ctrl+C` tại cửa sổ Uvicorn rồi chạy:

```powershell
Remove-Item -LiteralPath .\data\server.db -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath .\data\server.db-wal -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath .\data\server.db-shm -Force -ErrorAction SilentlyContinue
& .\.venv\Scripts\python.exe -m server.seed
```

Các lệnh xóa database demo là không thể hoàn tác. Quy trình reset cả hai phía và
kế hoạch Tuần 3 nằm tại [WEEK3_HANDOFF.md](WEEK3_HANDOFF.md).

## 8. Kế hoạch Tuần 3

Tuần 3 thực hiện F2 và F3: app controller theo tên process + SHA-256, DNS proxy và
SafeSearch, event outbox có idempotency, báo cáo phụ huynh và màn hình hoạt động
minh bạch cho trẻ. Trước khi thu thập event mới phải chốt schema tối thiểu dữ liệu,
retention và cleanup. Definition of done chi tiết nằm trong tài liệu bàn giao.
