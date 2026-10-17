# F5: bảo mật và quyền riêng tư

Tài liệu này đối chiếu F5 trang 8-9 của `QuanLyMayTinhTreEm.pdf` với mã hiện tại.
Các kiểm soát production như HSM, nhiều worker, installer ký số và audit bất biến
không được tuyên bố là đã có.

## Đối chiếu yêu cầu tối thiểu

| Hạng mục | Triển khai | Kiểm chứng |
|---|---|---|
| Xác thực phụ huynh | Argon2id; mật khẩu seed tối thiểu 10 ký tự; khóa 15 phút sau 5 lần sai; rate limit IP | `test_integration.py`, `test_units.py` |
| Phiên làm việc | Cookie HttpOnly, Secure khi HTTPS, SameSite=Lax; 12 giờ; logout xóa session server; CSRF cho thao tác ghi | `test_integration.py`, `test_f5_security.py` |
| Kênh truyền | Server HTTPS dùng TLS tối thiểu 1.2; agent bắt buộc pin SHA-256 chứng chỉ cho HTTPS; HTTP chỉ loopback hoặc ngoại lệ lab rõ ràng; WebSocket dùng Authorization header | `agent/transport_security.py`, `server/secure_run.py`, test F5 |
| Định danh thiết bị | Access 15 phút, refresh 30 ngày và xoay mỗi lần; gắn device ID; fingerprint chỉ giữ SHA-256; dashboard thu hồi cả access/refresh và đóng WebSocket | test integration và F5 |
| Dữ liệu lưu trữ | Mật khẩu/PIN Argon2id; token SHA-256; khóa ký policy AES-256-GCM từ biến môi trường; token/khóa agent DPAPI LocalMachine; không hardcode khóa | test F5 |
| Phân quyền | Ba ngữ cảnh tách biệt: `parent`, `child-view` bằng device token, và `admin` bằng cookie/session riêng; ownership tại query chống IDOR; admin chỉ xem metadata vận hành | test F5 và test truy cập chéo |
| Đặc quyền cục bộ | Setup yêu cầu tài khoản trẻ standard; ngoại lệ admin chỉ dành lab và phải bật rõ; Service LocalSystem; thư mục ProgramData chỉ SYSTEM/Administrators được ghi | script setup/install và test agent |
| Mô hình mối đe dọa | 12 dòng STRIDE, gồm trẻ là người tấn công và lạm dụng stalkerware | `THREATMODEL.md` |
| Chống lạm dụng | Tray hữu hình, tự khởi động; Service chỉ chờ tối đa 60 giây lúc khởi động và tự dừng khi mất heartbeat Tray quá 15 giây; thu thập tối thiểu; consent khi ghép | test F1/IPC, watchdog và checklist lab |

TOTP là điểm cộng theo đề và chưa được coi là yêu cầu tối thiểu. Administrator
production có MFA, audit bất biến và scoped support access vẫn là thiết kế đích.

## Cấu hình khóa và HTTPS

Tạo `.env`, rồi sinh hai khóa ngẫu nhiên thay vì sao chép khóa mẫu:

```powershell
Copy-Item .env.example .env
& .\scripts\Initialize-OGKSecrets.ps1
```

Chạy HTTPS bằng chứng chỉ PEM:

```powershell
& .\.venv\Scripts\python.exe -m server.secure_run --cert C:\certs\server.crt --key C:\certs\server.key
```

Lấy SHA-256 của chứng chỉ DER/PEM bằng công cụ quản trị tin cậy, kiểm tra ngoài
kênh, rồi truyền pin khi cài agent:

```powershell
& .\scripts\Setup-OGKAgent.ps1 -ServerUrl https://server.lab:8000 -CertificateSha256 <64-hex>
```

Agent kiểm tra pin trước mỗi nhóm kết nối HTTP và trước mỗi WebSocket. Sai pin thì
không gửi token. Khi xoay chứng chỉ phải phân phối pin mới có kiểm soát.

## Phạm vi sử dụng hợp pháp

Chỉ cha mẹ hoặc người giám hộ hợp pháp được cài OpenGuard Kids trên thiết bị họ có
quyền quản lý, sau khi đã thông báo rõ cho người sử dụng thiết bị. Không được cài
bí mật để theo dõi người lớn, người không thuộc phạm vi giám hộ hoặc máy của người
khác. Thu hồi thiết bị trên dashboard sẽ vô hiệu token; gỡ cài đặt phải khôi phục
cấu hình mạng và xóa dữ liệu agent theo quy trình cleanup.

## Checklist OWASP ASVS mức 1 (20 mục)

| # | Kiểm soát | Trạng thái/bằng chứng |
|---:|---|---|
| 1 | Không chứa credential mặc định trong mã | Đạt: `.env.example` để trống khóa/mật khẩu |
| 2 | Mật khẩu được băm mạnh | Đạt: Argon2id |
| 3 | Thông báo đăng nhập không lộ tài khoản tồn tại | Đạt: thông báo chung + dummy hash |
| 4 | Chống brute force | Đạt: khóa 5 lần/15 phút + rate limit |
| 5 | Session ID ngẫu nhiên đủ mạnh | Đạt: `secrets.token_urlsafe(32)` |
| 6 | Xoay session khi đăng nhập | Đạt |
| 7 | Logout vô hiệu session server | Đạt |
| 8 | Cookie HttpOnly | Đạt |
| 9 | Cookie Secure khi HTTPS | Đạt |
| 10 | Cookie SameSite | Đạt: Lax parent, Strict admin |
| 11 | CSRF cho thao tác ghi | Đạt |
| 12 | Kiểm tra ownership chống IDOR | Đạt, có test chéo tài khoản |
| 13 | Tách quyền parent/admin/device | Đạt, session/token độc lập |
| 14 | Validate input và từ chối trường thừa | Đạt: Pydantic `extra=forbid` |
| 15 | Security headers/CSP/frame protection | Đạt |
| 16 | Không cache response nhạy cảm | Đạt: `Cache-Control: no-store` |
| 17 | TLS 1.2+ ngoài loopback | Đạt trong secure runner và agent |
| 18 | Bí mật mã hóa/băm khi lưu | Đạt: AES-GCM, DPAPI, SHA-256 token |
| 19 | Audit hành động bảo mật | Đạt: policy, command, request, revoke |
| 20 | Không thu thập nội dung nhạy cảm | Đạt: schema/test loại URL, phím gõ, ảnh và nội dung |

## Nghiệm thu Windows bắt buộc

Test tự động không thay thế các bước: kiểm tra TLS/pin với chứng chỉ thật; sai pin
phải thất bại; xác nhận `remote-config.json` không chứa token rõ; thử thu hồi khi
agent đang online; xác nhận tài khoản trẻ standard không sửa được ProgramData hoặc
dừng Service. Đóng Tray phải làm Service chuyển sang `Stopped` trong tối đa 16 giây;
DNS/cấu hình trình duyệt phải được khôi phục và không còn tiến trình kiểm soát chạy ẩn.
