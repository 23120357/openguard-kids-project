# Mô hình mối đe dọa F5

Phạm vi là server FastAPI, dashboard, Windows Service, Tray UI, DNS proxy và dữ
liệu cục bộ. Bảng này dùng STRIDE và bao gồm hai kịch bản bắt buộc: trẻ là người
tấn công và sản phẩm bị lạm dụng thành stalkerware.

| STRIDE | Mối đe dọa | Kiểm soát đã triển khai | Giới hạn còn lại |
|---|---|---|---|
| Spoofing | Đoán mật khẩu phụ huynh | Argon2id, tối thiểu 10 ký tự khi seed, khóa 15 phút sau 5 lần sai, rate limit theo IP | Rate limit trong một process; TOTP là điểm cộng |
| Spoofing | Đoán/dùng lại mã ghép | Mã ngẫu nhiên 8 ký tự, 10 phút, dùng một lần, consent và rate limit | Chưa có limiter phân tán |
| Spoofing | Sao chép token thiết bị | Access 15 phút, refresh rotation, server chỉ giữ SHA-256; cấu hình agent bọc DPAPI LocalMachine | Cần quy trình phục hồi thiết bị khi cài lại Windows |
| Tampering | Sửa policy/cache | HMAC riêng từng thiết bị, version, agent từ chối chữ ký sai; khóa được mã hóa AES-GCM ở server | HMAC vẫn là khóa đối xứng; production nên dùng chữ ký bất đối xứng |
| Tampering | Giả mạo server | HTTPS TLS 1.2+, pin SHA-256 chứng chỉ trước HTTP/WebSocket | Đổi chứng chỉ cần phân phối pin mới có kiểm soát |
| Repudiation | Phủ nhận đổi luật hoặc thu hồi máy | Audit actor, UTC, IP, giá trị cũ/mới; trẻ xem audit theo hồ sơ | SQLite/audit development chưa bất biến như append-only log production |
| Information disclosure | Phụ huynh A xem dữ liệu B | Ownership tại query, CSRF, cookie HttpOnly/SameSite, test truy cập chéo | Cần kiểm tra lại khi thêm API mới |
| Information disclosure | Đọc token/khóa trên đĩa | Token server chỉ giữ hash; khóa DB AES-GCM; agent DPAPI + ACL SYSTEM/Admin | Bản sao lưu ngoài ứng dụng cần mã hóa riêng |
| Denial of service | Gửi dồn login/enroll/refresh | Rate limit và giới hạn schema/body | Một process, chưa có shared limiter |
| Elevation of privilege | Trẻ sửa cấu hình, đổi app hoặc kill agent | Tài khoản standard được kiểm tra khi setup, ACL, Service LocalSystem, SHA-256 app, SCM restart, policy cache có chữ ký | Administrator vẫn có thể vượt; không tuyên bố chống bypass tuyệt đối |
| Elevation of privilege | Trẻ đổi DNS/DoH/VPN/boot USB | Agent cấu hình DNS/Secure DNS, lưu và khôi phục cấu hình | DoH/DoT, VPN, Safe Mode và boot USB vẫn là giới hạn cần trình bày trong báo cáo M3 |
| Information disclosure | Dùng sản phẩm theo dõi người lớn | Tray luôn hiện; Service tự dừng khi thiếu heartbeat Tray; không lưu URL, phím gõ, nội dung hoặc ảnh; dashboard có thu hồi thiết bị | Bộ cài thử nghiệm chưa ký số; chỉ dùng đúng phạm vi có consent |

Kiểm chứng chi tiết, checklist ASVS và quy trình TLS/DPAPI nằm trong
`F5_SECURITY.md`.
