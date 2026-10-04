# F1 — kiểm soát thời gian và chiến lược kiểm thử

Tài liệu này áp dụng cho Windows Service và Tray UI phát triển. Policy F1 cục bộ
nằm tại `%ProgramData%\OpenGuardKids\f1-policy.json`; trạng thái và sự kiện nằm
trong `f1-state.db`. File mặc định **tắt enforcement** để không vô tình khóa máy
phát triển. Chỉ script cấu hình test mới bật policy.

## Phạm vi đã triển khai

- Quota ngày thường và cuối tuần độc lập.
- Lịch tuần 7 ngày × 48 ô nửa giờ theo múi giờ Windows cục bộ.
- Chỉ đếm khi Tray đang hiện diện, phiên chưa khóa, máy chưa idle 5 phút và lịch
  cho phép. Đồng hồ monotonic quyết định lượng thời gian cộng vào quota.
- Cảnh báo một lần tại 10, 5 và 1 phút; hết quota có 60 giây để lưu công việc.
- Tray trong phiên tương tác gọi `LockWorkStation`; Service chạy LocalSystem không
  cố điều khiển desktop từ Session 0.
- Đồng hồ tin cậy không lùi. Lùi đồng hồ hệ thống 3 giờ không tạo thêm quota và
  sinh sự kiện `clock_tamper`.
- Usage, grace deadline, cảnh báo và sự kiện sống qua lần restart Service.

Chưa làm phần F1 “nên có” về ngân sách theo nhóm ứng dụng, vì cần bộ phân loại
process của F2. Thời gian thưởng theo nhiệm vụ cũng chưa có. Policy F1 từ server đã
nối vào Service, có version/HMAC và cache offline. Script `Set-OGKF1TestPolicy.ps1`
chỉ còn dùng cho demo F1 cục bộ chưa ghép server.

## Các lớp kiểm thử

| Lớp | Mục tiêu | Chạy ở đâu |
|---|---|---|
| Unit state machine | Quota, lịch, idle/lock, grace, rollback, persistence | pytest, không khóa máy thật |
| IPC integration | Validation heartbeat, UI presence timeout, event acknowledgement | pytest |
| Service smoke | SCM, LocalSystem, ACL, named pipe, reload policy | Windows VM |
| Acceptance | Thời gian thực và khóa Windows thật | Windows VM dùng riêng |

Chạy bộ tự động:

```powershell
& .\.venv-service\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\ruff.exe check .
& .\.venv\Scripts\ruff.exe format --check .
```

Kết quả tại mốc bàn giao cuối Tuần 2: `140 passed`. Test dùng database tạm, không
thay đổi database demo. Cảnh báo deprecation của Starlette TestClient chưa làm test
thất bại và cần xử lý khi nâng dependency.

Các test F1 dùng đồng hồ mô phỏng, nên một giờ sử dụng được kiểm tra trong dưới một
giây và không thay đổi đồng hồ/khóa phiên thật. Tiêu chí tự động gồm:

- quota weekday/weekend và ánh xạ đúng ô nửa giờ;
- yêu cầu khóa ngay heartbeat đầu tiên ngoài lịch;
- sai số đếm một giờ không quá 1 giây, chặt hơn yêu cầu ±30 giây/giờ;
- idle từ 300 giây, session locked, thiếu Tray và gap heartbeat lớn không bị đếm;
- đúng ba cảnh báo, không lặp; grace 60 giây rồi mới yêu cầu khóa;
- rollback 3 giờ không reset ngày hoặc tăng quota, chỉ ghi một event;
- restart giữa grace vẫn khóa đúng hạn; event có thể acknowledge.

## Chuẩn bị nghiệm thu trên Windows

Chỉ làm trên VM/laptop lab đã lưu mọi công việc. Mở PowerShell quản trị:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& .\scripts\Install-OGKTestService.ps1
& .\scripts\Set-OGKF1TestPolicy.ps1
```

Sau đó, ở PowerShell người dùng bình thường:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& .\scripts\Start-OGKTray.ps1 -Open
```

Chạy lại đúng lệnh này không tạo process, icon hoặc cửa sổ thứ hai. Script gửi một
named-event để cửa sổ hiện có được restore/foreground; bản thân Tray còn giữ global
mutex để chặn race giữa nhiều lệnh start.

Policy test mặc định là 3 phút cho cả weekday/weekend, cho phép toàn bộ lịch. Đổi
policy sẽ tăng `version`, reset usage về 0 và restart Service để reload. Vì vậy mỗi
lần chạy script, đồng hồ luôn bắt đầu từ đúng allocation mới (mặc định `00:03:00`),
không trừ usage của lần demo trước. Nếu Tray đã chạy, script giữ nguyên instance đó;
không mở Tray thứ hai và chỉ làm đồng hồ nhận policy mới. Không sửa file trong
ProgramData bằng tài khoản trẻ.

Reset được thực hiện ngay trong constructor của Service, trước heartbeat đầu tiên.
Sau khi Service chạy lại, script signal refresh event của Tray. Vì vậy chuyển từ
policy disabled sang enabled trên một Tray vừa khởi động cũng phải hiện `00:03:00`;
không phụ thuộc vào nhịp retry của named pipe.

Nếu shell báo không nhận diện lệnh `powershell`, không gọi một PowerShell khác từ
bên trong shell hiện tại. Dùng toán tử `&` như các lệnh trên. Với PowerShell 7,
`pwsh -File ...` cũng dùng được nhưng không cần thiết.

Tray hiển thị thời gian còn lại theo đồng hồ số `HH:MM:SS`. Nút
**Demo developer: giảm 1 phút** trừ 60 giây khỏi quota để đi nhanh tới các mốc cảnh
báo, grace và khóa máy; mỗi lần bấm được ghi thành event cục bộ.

State và mọi event trong SQLite có `recorded_at` dạng ISO 8601 UTC, ví dụ
`2026-10-03T10:30:00Z`, ngoài Unix `ts` dùng cho tính toán. Chạy
`python -m agent.f1_diagnostics` để xem cả ngày và giờ đã ghi.

## Invariant singleton của milestone

- Một policy hoạt động: `%ProgramData%\OpenGuardKids\f1-policy.json`, thay atomically.
- Một Windows Service: SCM name cố định `OpenGuardKidsAgentTest`.
- Một Tray process/icon toàn máy: global named mutex.
- Một cửa sổ thuộc Tray đó; đóng chỉ ẩn xuống notification area, chạy start lại chỉ
  mở cửa sổ hiện có.

## Kịch bản nghiệm thu

### A. Quota, cảnh báo và grace

1. Cấu hình quota 11 phút để quan sát đủ ba cảnh báo:

   ```powershell
   .\scripts\Set-OGKF1TestPolicy.ps1 -WeekdayMinutes 11 -WeekendMinutes 11
   ```

2. Giữ phiên hoạt động. Xác nhận cảnh báo xuất hiện khi còn 10, 5, 1 phút, mỗi mốc
   đúng một lần.
3. Khi quota về 0, UI phải hiển thị 60 giây lưu công việc và chưa khóa ngay.
4. Hết 60 giây, Windows phải khóa. Độ trễ kỳ vọng tối đa 2 giây với heartbeat 1
   giây; ngưỡng pass của đề là khóa đúng lúc sau grace.
5. Đăng nhập lại. Trong bản demo, cùng một lần hết quota không được khóa lần thứ
   hai. Cờ hoàn tất khóa được Service lưu bền vững và reset khi sang ngày/policy mới.

Có thể dùng quota 3 phút để smoke test nhanh; lúc này chỉ mốc 1 phút áp dụng vì
các mốc 10 và 5 lớn hơn toàn bộ quota.

### B. Lịch 7×48 và yêu cầu dưới 5 giây

Trong PowerShell quản trị:

```powershell
.\scripts\Set-OGKF1TestPolicy.ps1 -ScheduleMode BlockCurrentSlot
```

Bắt đầu bấm giờ khi Service trở lại `Running`. Tray phải yêu cầu khóa ở heartbeat
kế tiếp, dưới 5 giây. Mở khóa máy rồi lập tức trả policy về `AllowAll` để tránh bị
khóa lại:

```powershell
.\scripts\Set-OGKF1TestPolicy.ps1 -ScheduleMode AllowAll
```

Lặp ở một ranh giới `:00` hoặc `:30` để xác nhận đổi ô lịch đúng giờ cục bộ.

### C. Idle và khóa phiên không bị tính

1. Ghi `used_seconds` bằng PowerShell quản trị:

   ```powershell
   .\.venv-service\Scripts\python.exe -m agent.f1_diagnostics
   ```

2. Không chạm chuột/phím ít nhất 6 phút. Một phần trước mốc 5 phút vẫn được tính;
   khoảng thời gian sau mốc 5 phút phải không tăng.
3. Khóa Windows 2 phút rồi mở lại. `used_seconds` không được tăng trong khoảng đã
   khóa.
4. Thoát Tray trong 30 giây. Service phải báo `inert_no_tray`, không đếm và không
   yêu cầu khóa. Đây là kiểm tra ranh giới chống chạy ẩn, không phải cơ chế chống
   bypass production.

### D. Sai số một giờ

Đặt quota ít nhất 120 phút, giữ máy hoạt động trong 60 phút bằng thao tác lab hợp
pháp, rồi so sánh `used_seconds` với đồng hồ độc lập. Pass khi sai số không quá 30
giây. Ghi riêng mọi lần sleep, RDP disconnect hoặc mất Tray; các gap trên 5 giây
cố ý không được tính nên không thuộc mẫu “hoạt động liên tục”.

### E. Lùi đồng hồ 3 giờ

Chỉ chạy trên VM disposable và chụp snapshot trước. Tắt đồng bộ thời gian, ghi
quota còn lại, lùi đồng hồ Windows đúng 3 giờ, tiếp tục dùng 1–2 phút rồi chạy
diagnostics. Pass khi:

- `local_date` không lùi và quota không tăng/reset;
- `clock_tamper_active` là true;
- có event `clock_tamper` với observed/trusted time;
- quota tiếp tục giảm theo monotonic time.

Khôi phục đúng giờ và bật lại đồng bộ ngay sau test.

### F. Restart và dữ liệu

Restart Service trong lúc đang dùng và trong 60 giây grace. Usage không reset;
deadline grace không kéo dài. Kiểm tra thư mục ProgramData chỉ cấp Full Control cho
SYSTEM và Administrators. Policy JSON sai schema phải khiến F1 tắt an toàn và UI
hiển thị lỗi, không tự suy đoán policy.

## Thu dọn

Mở PowerShell quản trị:

```powershell
& .\scripts\Cleanup-OGKTestService.ps1 -RemoveAgentData
```

Thêm `-RemoveRuntime` nếu muốn xóa môi trường Python của service. `-RemoveAgentData`
xóa vĩnh viễn policy, usage và event history trong đúng thư mục ProgramData của
OpenGuard Kids.

## Điều kiện trước production

Không xem F1 hiện tại là chống bypass. Production cần policy được ký từ server,
DPAPI/device key, kiểm chứng caller của named pipe, chống sửa/gỡ service, per-session
Tray watchdog, xử lý multi-session/RDP, installer ký số, SCM recovery và test trên
các phiên bản Windows hỗ trợ. Heartbeat activity do Tray cung cấp là ranh giới tin
cậy tạm thời của development milestone.

Ngoài ra phải quyết định hành vi khi chưa có child đăng nhập. Hiện kết thúc phiên
trong Tray đưa F1 về `awaiting_profile`, vì vậy đây chưa phải cơ chế chống bypass.
