# Kiểm chứng toàn bộ yêu cầu bắt buộc F1-F5

Tài liệu này là checklist nghiệm thu cho `QuanLyMayTinhTreEm.pdf`. Chạy trên
Windows 10/11 lab hoặc máy ảo, từ thư mục gốc repository. Lưu mọi công việc trước
khi thử khóa Windows. Các bước đổi giờ hệ thống, DNS và xóa tài khoản chỉ được làm
trên máy/tài khoản thử nghiệm.

## 0. Quy ước và chuẩn bị

- **PowerShell thường**: cửa sổ của tài khoản trẻ đang đăng nhập.
- **PowerShell quản trị**: mở bằng **Run as administrator**.
- Giữ Tray hiện rõ ở notification area trong suốt lúc Agent chạy.
- Với mọi bước thủ công, lưu ảnh hoặc log kèm thời điểm bắt đầu/kết thúc.

Trong PowerShell thường:

```powershell
Set-Location "C:\Users\huyen\source\repos\openguard-kids-project"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    python -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install -r .\requirements-lock.txt

if (-not (Test-Path .\.env)) {
    Copy-Item .\.env.example .\.env
    & .\scripts\Initialize-OGKSecrets.ps1
}

$testPython = if (Test-Path .\.venv-service\Scripts\python.exe) {
    (Resolve-Path .\.venv-service\Scripts\python.exe).Path
} else {
    (Resolve-Path .\.venv\Scripts\python.exe).Path
}
```

Chạy toàn bộ kiểm thử tự động trước khi nghiệm thu thủ công:

```powershell
& $testPython -m pytest -q --basetemp=.\.codex-build\pytest-f1-f5 -p no:cacheprovider
& .\.venv\Scripts\ruff.exe check .
& .\.venv\Scripts\ruff.exe format --check .
node --check .\dashboard\static\app.js
```

Kết quả chuẩn hiện tại:

- `266 passed`;
- Ruff không báo lỗi;
- JavaScript không báo lỗi cú pháp;
- một cảnh báo deprecation của Starlette TestClient được phép xuất hiện.

## 1. Khởi động hệ thống tích hợp

### 1.1 Server và Dashboard

Trong PowerShell thường:

```powershell
& .\.venv\Scripts\python.exe -m server.seed
& .\.venv\Scripts\python.exe -m uvicorn server.app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Giữ cửa sổ này mở. Mở `http://127.0.0.1:8000` và đăng nhập bằng tài khoản demo
trong `.env`. Giá trị mặc định của bản mẫu là:

- email: `parent@example.test`;
- mật khẩu: `ChangeMe-ForLocalDemo123!`.

Trong cửa sổ PowerShell khác:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

PASS khi trả về `status = ok`.

### 1.2 Cài Service, mở Tray và ghép thiết bị

Trên Dashboard, tạo hồ sơ trẻ và PIN 6 số, sau đó tạo mã ghép đôi. Trong
PowerShell thường của tài khoản trẻ:

```powershell
& .\scripts\Setup-OGKAgent.ps1
```

Chấp nhận UAC, nhập mã ghép đôi trên Tray, rồi đăng nhập hồ sơ trẻ. Kiểm tra:

```powershell
Get-Service OpenGuardKidsAgentTest
& .\.venv-service\Scripts\python.exe -m agent.windows_service ping
```

PASS khi Service là `Running`, named pipe trả `pong`, chỉ có một Tray icon và
Dashboard hiển thị thiết bị trực tuyến.

## 2. F1 - Kiểm soát thời gian

### 2.1 Kiểm thử tự động F1

```powershell
& .\.venv-service\Scripts\python.exe -m pytest tests\test_time_control.py tests\test_agent_ipc.py tests\test_agent_setup_flow.py tests\test_ui_scheduler.py -q --basetemp=.\.codex-build\pytest-f1 -p no:cacheprovider
```

### 2.2 Quota, cảnh báo và grace 60 giây

Trong PowerShell quản trị:

```powershell
& .\scripts\Set-OGKF1TestPolicy.ps1 -WeekdayMinutes 11 -WeekendMinutes 11 -ScheduleMode AllowAll
```

Trong PowerShell thường:

```powershell
& .\scripts\Start-OGKTray.ps1 -Open
```

Giữ phiên hoạt động. PASS khi:

- cảnh báo xuất hiện đúng một lần ở mốc còn 10, 5 và 1 phút;
- hết quota có đúng 60 giây để lưu công việc;
- hết grace Windows bị khóa;
- mở khóa khi vẫn hết quota thì bị khóa lại;
- khởi động lại Service không làm quota hoặc grace quay về ban đầu.

Xem trạng thái và sự kiện:

```powershell
& .\.venv-service\Scripts\python.exe -m agent.f1_diagnostics
```

### 2.3 Lịch 7 x 48 và khóa dưới 5 giây

Lưu công việc trước khi chạy. Trong PowerShell quản trị:

```powershell
$started = Get-Date
& .\scripts\Set-OGKF1TestPolicy.ps1 -ScheduleMode BlockCurrentSlot
Get-Service OpenGuardKidsAgentTest
```

PASS khi Tray yêu cầu khóa ở heartbeat kế tiếp và Windows khóa trong dưới 5 giây
tính từ lúc Service trở lại `Running`. Khôi phục ngay sau khi đăng nhập lại:

```powershell
& .\scripts\Set-OGKF1TestPolicy.ps1 -ScheduleMode AllowAll
```

Lặp tại ranh giới phút `:00` hoặc `:30` để xác nhận đúng ô lịch địa phương.

### 2.4 Idle, khóa phiên và độ chính xác

Ghi số liệu ban đầu:

```powershell
& .\.venv-service\Scripts\python.exe -m agent.f1_diagnostics
```

Không dùng chuột/phím ít nhất 6 phút, rồi chạy lại lệnh trên. PASS khi thời gian
sau ngưỡng idle 5 phút không được cộng. Khóa Windows 2 phút bằng:

```powershell
rundll32.exe user32.dll,LockWorkStation
```

Sau khi đăng nhập lại, chạy diagnostics. PASS khi 2 phút khóa không được cộng.

Để đo sai số một giờ, đặt quota ít nhất 120 phút và cho phép toàn bộ lịch:

```powershell
& .\scripts\Set-OGKF1TestPolicy.ps1 -WeekdayMinutes 120 -WeekendMinutes 120 -ScheduleMode AllowAll
$measurementStart = Get-Date
& .\.venv-service\Scripts\python.exe -m agent.f1_diagnostics
```

Dùng máy liên tục trong 60 phút, không sleep/idle/khóa/mất Tray, rồi chạy:

```powershell
$measurementEnd = Get-Date
$measurementEnd - $measurementStart
& .\.venv-service\Scripts\python.exe -m agent.f1_diagnostics
```

PASS khi mức tăng `used_seconds` lệch không quá 30 giây so với thời gian đo.

### 2.5 Chống lùi đồng hồ

Chỉ chạy trên VM đã snapshot. Trong PowerShell quản trị:

```powershell
Stop-Service W32Time -ErrorAction SilentlyContinue
$beforeRollback = Get-Date
Set-Date -Date $beforeRollback.AddHours(-3)
Start-Sleep -Seconds 90
& .\.venv-service\Scripts\python.exe -m agent.f1_diagnostics
```

PASS khi `local_date` không lùi, quota không tăng/reset,
`clock_tamper_active = true`, có sự kiện `clock_tamper`, và usage vẫn giảm theo
đồng hồ monotonic. Khôi phục thời gian ngay:

```powershell
Set-Service W32Time -StartupType Automatic
Start-Service W32Time
w32tm.exe /resync /force
Get-Date
```

### 2.6 Tray bắt buộc tồn tại

Thoát Tray bằng menu **Thoát** rồi chạy:

```powershell
$deadline = (Get-Date).AddSeconds(16)
do {
    $service = Get-Service OpenGuardKidsAgentTest
    $service
    if ($service.Status -eq 'Stopped') { break }
    Start-Sleep -Seconds 1
} while ((Get-Date) -lt $deadline)
```

PASS khi Service chuyển thành `Stopped` trong tối đa 16 giây. Kiểm tra khởi động
Service mà không có Tray:

```powershell
Start-Service OpenGuardKidsAgentTest
Start-Sleep -Seconds 61
Get-Service OpenGuardKidsAgentTest
```

PASS khi Service tự dừng. Mở lại đúng một Tray:

```powershell
& .\scripts\Start-OGKTray.ps1 -Restart -Open
Start-Service OpenGuardKidsAgentTest
```

## 3. F2 - Kiểm soát ứng dụng và website

### 3.1 Kiểm thử tự động và DNS cô lập

```powershell
& .\.venv-service\Scripts\python.exe -m pytest tests\test_f2_filtering.py tests\test_activity_events.py tests\test_web_protection.py tests\test_tray_ui.py -q --basetemp=.\.codex-build\pytest-f2 -p no:cacheprovider
& .\.venv-service\Scripts\python.exe -m scripts.check_f2_dns --output output\f2-dns.json
Get-Content .\output\f2-dns.json | Select-String 'blocked_pass|education_pass|passed'
```

PASS khi có ít nhất 48/50 miền chặn, đúng 20/20 miền giáo dục được phép và
`passed` là `true`. Chuẩn hiện tại là 50/50 và 20/20.

Kiểm tra kích thước và phân bố bảng phân loại:

```powershell
$domains = Import-Csv .\common\domain_categories.csv
$domains.Count
$domains | Group-Object category | Sort-Object Name | Select-Object Name,Count
$domains | Group-Object review_status | Select-Object Name,Count
```

PASS khi có từ 200 đến 500 mục thật, đủ các nhóm trong đề và trạng thái rà soát
được ghi rõ. Dataset hiện có 311 mục thật và một fixture `.test`.

### 3.2 Chặn ứng dụng bằng SHA-256, kể cả đổi tên

Dùng một executable lab không có dữ liệu quan trọng:

```powershell
& .\.venv-service\Scripts\python.exe -m agent.filtering C:\Lab\sample.exe
Get-FileHash -Algorithm SHA256 C:\Lab\sample.exe
Copy-Item C:\Lab\sample.exe C:\Lab\game.exe
Copy-Item C:\Lab\sample.exe C:\Lab\explorer.exe
```

Thêm hash vào danh sách chặn trên Dashboard rồi chạy hai bản sao:

```powershell
Start-Process C:\Lab\game.exe
Start-Sleep -Seconds 3
Get-Process game -ErrorAction SilentlyContinue
Start-Process C:\Lab\explorer.exe
Start-Sleep -Seconds 3
Get-Process explorer -ErrorAction SilentlyContinue | Select-Object Id,Path
```

PASS khi hai bản sao trong `C:\Lab` bị kết thúc, Tray hiện lý do, lịch sử có sự
kiện chặn và `C:\Windows\explorer.exe` thật không bị tác động.

### 3.3 DNS proxy, nhóm website và SafeSearch

Kiểm tra cổng DNS và cấu hình adapter trong PowerShell quản trị:

```powershell
Get-NetUDPEndpoint -LocalPort 53 -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,OwningProcess
Get-NetTCPConnection -LocalPort 53 -State Listen -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,OwningProcess
Get-DnsClientServerAddress | Format-Table InterfaceAlias,AddressFamily,ServerAddresses -AutoSize
```

Sau khi Service đã cấu hình DNS và policy lab đã được áp dụng:

```powershell
& .\.venv-service\Scripts\python.exe -m scripts.check_f2_dns --live --output output\f2-dns-live.json
Clear-DnsClientCache
nslookup -type=A www.google.com 127.0.0.1
nslookup -type=AAAA www.google.com.vn 127.0.0.1
nslookup -type=CNAME www.bing.com 127.0.0.1
```

PASS khi policy có đủ sáu nhóm, tên miền con kế thừa luật, Google trả alias
`forcesafesearch.google.com`, Bing trả `strict.bing.com`, và trình duyệt thể hiện
SafeSearch bị cưỡng chế. Không tìm nội dung người lớn để thử.

## 4. F3 - Ghi nhận, báo cáo và xóa dữ liệu

### 4.1 Kiểm thử tự động F3

```powershell
& .\.venv-service\Scripts\python.exe -m pytest tests\test_activity_events.py tests\test_f3_reports.py tests\test_tray_ui.py tests\test_integration.py -q --basetemp=.\.codex-build\pytest-f3 -p no:cacheprovider
```

### 4.2 Tạo dữ liệu mẫu và kiểm tra báo cáo

Khi trẻ đã đăng nhập trên Tray:

```powershell
Resolve-DnsName -Name example.test -Server 127.0.0.1 -Type A -DnsOnly -ErrorAction SilentlyContinue
Start-Sleep -Seconds 6
Resolve-DnsName -Name example.test -Server 127.0.0.1 -Type AAAA -DnsOnly -ErrorAction SilentlyContinue
Start-Sleep -Seconds 6
Resolve-DnsName -Name another.test -Server 127.0.0.1 -Type A -DnsOnly -ErrorAction SilentlyContinue
```

Mở một ứng dụng lab vài phút rồi đóng. PASS khi:

- Tray **Hôm nay** có thời gian, Top ứng dụng và tên miền;
- Dashboard có biểu đồ ngày/tuần, Top 10, lượt chặn và yêu cầu;
- đổi hồ sơ không làm lộ dữ liệu hồ sơ khác;
- xuất PDF tuần thành công và response không bị cache.

### 4.3 Retention và nút xóa dữ liệu hoạt động

Trên Dashboard chọn hồ sơ thử nghiệm và bấm **Xóa toàn bộ dữ liệu hoạt động của
con tôi**. PASS khi báo cáo về 0, quota/PIN/policy vẫn còn. Nếu Agent ngoại tuyến,
Dashboard phải hiện thiết bị đang chờ; mở lại Agent và chờ trạng thái hoàn tất.

Kiểm tra API bằng bộ test chuyên biệt:

```powershell
& .\.venv-service\Scripts\python.exe -m pytest tests\test_f3_reports.py -k "erasure or retention" -q --basetemp=.\.codex-build\pytest-f3-delete -p no:cacheprovider
```

### 4.4 Xóa toàn bộ tài khoản và thiết bị

Chỉ dùng tài khoản demo. Trên Dashboard nhập lại mật khẩu và bấm **Xóa toàn bộ
tài khoản và thiết bị**. PASS khi bị đăng xuất, toàn bộ hồ sơ/thiết bị biến mất,
token Agent cũ không kết nối hoặc refresh được, và tài khoản khác không bị ảnh hưởng.

```powershell
& .\.venv-service\Scripts\python.exe -m pytest tests\test_integration.py::test_delete_account_removes_household_and_invalidates_devices -q --basetemp=.\.codex-build\pytest-account-delete -p no:cacheprovider
```

Tạo lại dữ liệu demo sau phép thử xóa:

```powershell
& .\.venv\Scripts\python.exe -m server.seed
```

## 5. F4 - Dashboard, đồng bộ và điều khiển từ xa

### 5.1 Kiểm thử tự động F4

```powershell
& .\.venv-service\Scripts\python.exe -m pytest tests\test_child_profiles.py tests\test_f4_remote.py tests\test_realtime_updates.py tests\test_integration.py -q --basetemp=.\.codex-build\pytest-f4 -p no:cacheprovider
```

### 5.2 Health, Service và kết nối

```powershell
Get-Service OpenGuardKidsAgentTest
& .\.venv-service\Scripts\python.exe -m agent.windows_service ping
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

PASS khi Service `Running`, pipe trả `pong`, Server `ok`, Dashboard báo thiết bị
trực tuyến và Tray báo đã kết nối.

### 5.3 Policy Dashboard tới Agent trong 60 giây

Bắt đầu đồng hồ trong PowerShell:

```powershell
$policyStarted = Get-Date
Write-Host "Bắt đầu lưu policy lúc $policyStarted"
```

Trên Dashboard đặt quota 3 phút, bật kiểm soát, cho phép ô lịch hiện tại và bấm
**Lưu chính sách**. Khi Tray đổi version, chạy:

```powershell
$policyFinished = Get-Date
$policyFinished - $policyStarted
```

PASS khi không quá 60 giây, policy version tăng, remaining bằng quota mới trừ
usage hiện tại và audit có old/new values.

### 5.4 Khóa ngay và cộng giờ dưới 5 giây

Lưu công việc trước. Trong PowerShell:

```powershell
$commandStarted = Get-Date
Write-Host "Bấm Khóa ngay trên Dashboard lúc $commandStarted"
```

Bấm **Khóa ngay** trên Dashboard. Sau khi đăng nhập lại:

```powershell
$commandFinished = Get-Date
$commandFinished - $commandStarted
```

PASS khi dưới 5 giây và audit có cả lúc gửi lệnh/lúc Agent xác nhận. Lặp với nút
**Cộng phút**: remaining tăng đúng số phút trong dưới 5 giây, usage không reset,
refresh/reconnect không cộng lần hai.

### 5.5 Yêu cầu thêm giờ và offline cache

Trên Tray gửi yêu cầu thêm giờ; Dashboard phải tự hiện trong vài giây. Duyệt hoặc
từ chối và xác nhận Tray nhận đúng kết quả. Để kiểm tra policy cache offline,
nhấn `Ctrl+C` trong đúng cửa sổ Uvicorn đã mở ở mục 1.1; không kết thúc hàng loạt
tiến trình Python. Sau đó kiểm tra Service:

```powershell
Get-Service OpenGuardKidsAgentTest
& .\.venv-service\Scripts\python.exe -m agent.windows_service ping
```

PASS khi Agent tiếp tục áp dụng policy đã ký trong cache. Khởi động lại server
bằng lệnh ở mục 1.1.

Kiểm tra từ chối cache bị sửa, chỉ trên máy lab:

```powershell
Stop-Service OpenGuardKidsAgentTest
notepad "$env:ProgramData\OpenGuardKids\remote-policy.json"
Start-Service OpenGuardKidsAgentTest
```

Sửa một giá trị nhưng không sửa signature. PASS khi policy bị từ chối, F1 tắt an
toàn và Tray báo lỗi. Khởi động lại server để Agent tải bản hợp lệ.

## 6. F5 - Bảo mật và quyền riêng tư

### 6.1 Kiểm thử tự động F5

```powershell
& .\.venv-service\Scripts\python.exe -m pytest tests\test_f5_security.py tests\test_integration.py tests\test_agent_setup_flow.py -q --basetemp=.\.codex-build\pytest-f5 -p no:cacheprovider
```

### 6.2 TLS 1.2+ và certificate pinning

Chuẩn bị chứng chỉ PEM thật hoặc chứng chỉ lab đã tin cậy, rồi chạy:

```powershell
& .\.venv\Scripts\python.exe -m server.secure_run --cert C:\certs\server.crt --key C:\certs\server.key --host 0.0.0.0 --port 8000
```

Lấy SHA-256 của chứng chỉ DER:

```powershell
certutil.exe -hashfile C:\certs\server.der SHA256
```

Bỏ khoảng trắng để được đúng 64 ký tự hex, rồi cài Agent:

```powershell
$certificatePin = '<64-hex-sha256>'
& .\scripts\Setup-OGKAgent.ps1 -ServerUrl https://server.lab:8000 -CertificateSha256 $certificatePin
```

PASS khi đúng pin thì ghép/đồng bộ được. Thử sai một ký tự:

```powershell
$replacement = if ($certificatePin[-1] -eq '0') { '1' } else { '0' }
$wrongPin = $certificatePin.Substring(0, 63) + $replacement
& .\scripts\Setup-OGKAgent.ps1 -ServerUrl https://server.lab:8000 -CertificateSha256 $wrongPin
```

Thử sai pin trên snapshot/cài đặt Agent sạch; `Setup-OGKAgent.ps1` không ghi đè
remote config của thiết bị đã ghép. PASS khi kết nối bị từ chối và token không
được gửi. Khôi phục snapshot hoặc cleanup dữ liệu lab rồi cài lại bằng pin đúng.

### 6.3 DPAPI, khóa bí mật và ACL

Trong PowerShell quản trị:

```powershell
$remoteConfig = "$env:ProgramData\OpenGuardKids\remote-config.json"
Get-Content -LiteralPath $remoteConfig
Select-String -LiteralPath $remoteConfig -Pattern 'access_token|refresh_token|policy_signing_key'
icacls.exe "$env:ProgramData\OpenGuardKids"
```

PASS khi file chỉ có `format = dpapi-local-machine-v1` và `blob`, không có token
hoặc policy key dạng rõ; thư mục chỉ cho `SYSTEM` và `Administrators` ghi.

Trong PowerShell thường của tài khoản trẻ standard:

```powershell
whoami.exe /groups | Select-String 'S-1-5-32-544'
sc.exe stop OpenGuardKidsAgentTest
```

PASS khi tài khoản không thuộc Administrators và không thể dừng Service hoặc sửa
file trong ProgramData.

### 6.4 Session, CSRF, ownership, revoke và phân quyền

Các kiểm soát này được kiểm tra bằng:

```powershell
& .\.venv-service\Scripts\python.exe -m pytest tests\test_f5_security.py tests\test_integration.py -k "login or csrf or ownership or revoke or admin or delete_account" -q --basetemp=.\.codex-build\pytest-f5-auth -p no:cacheprovider
```

Trên Dashboard bấm **Thu hồi thiết bị** khi Agent đang online. PASS khi WebSocket
đóng, access/refresh token cũ không còn dùng được và thiết bị phải ghép lại.

### 6.5 Không chạy ẩn khi mất Tray

Lặp lại mục 2.6. PASS khi đóng/mất Tray làm Service dừng trong tối đa 16 giây;
khởi động Service không có Tray làm Service dừng trong tối đa 60 giây; DNS và cấu
hình trình duyệt được khôi phục.

### 6.6 Xác nhận dữ liệu thu thập tối thiểu

```powershell
& .\.venv-service\Scripts\python.exe -m pytest tests\test_activity_events.py tests\test_f3_reports.py -q --basetemp=.\.codex-build\pytest-f5-privacy -p no:cacheprovider
Select-String -Path .\docs\PRIVACY.md -Pattern 'URL đầy đủ|phím|ảnh chụp|nội dung'
```

PASS khi event chỉ có bảy trường bắt buộc và không lưu URL đầy đủ, query string,
phím gõ, nội dung tin nhắn/tài liệu hoặc ảnh chụp màn hình.

## 7. Tổng hợp kết quả

Chạy lần cuối:

```powershell
& .\.venv-service\Scripts\python.exe -m pytest -q --basetemp=.\.codex-build\pytest-final-f1-f5 -p no:cacheprovider
& .\.venv\Scripts\ruff.exe check .
& .\.venv\Scripts\ruff.exe format --check .
node --check .\dashboard\static\app.js
Get-Service OpenGuardKidsAgentTest
```

Đánh dấu F1-F5 đạt khi:

- tất cả test tự động đạt;
- các phép đo F1/F4 đạt ngưỡng thời gian;
- F2 chặn ứng dụng theo hash và DNS/SafeSearch đạt;
- F3 báo cáo, retention, hai mức xóa dữ liệu đạt;
- F5 TLS/pin, DPAPI, ACL, revoke, quyền truy cập và Tray watchdog đạt;
- mọi lỗi/ảnh hưởng môi trường đã được khôi phục.

## 8. Thu dọn máy lab

Trong PowerShell quản trị:

```powershell
& .\scripts\Cleanup-OGKTestService.ps1 -RemoveAgentData
```

Thêm `-RemoveRuntime` nếu muốn xóa luôn môi trường Python của Service:

```powershell
& .\scripts\Cleanup-OGKTestService.ps1 -RemoveAgentData -RemoveRuntime
```

`-RemoveAgentData` xóa vĩnh viễn dữ liệu Agent trong thư mục OpenGuard Kids của
ProgramData. Không chạy trên máy có dữ liệu cần giữ.
