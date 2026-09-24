# Mô hình mối đe dọa ban đầu

Phạm vi: demo loopback với dữ liệu giả. Chưa đánh giá đạt ASVS hoặc sẵn sàng triển khai.

| STRIDE | Tình huống | Kiểm soát hiện có | Phần còn thiếu |
|---|---|---|---|
| Spoofing | Đoán mật khẩu phụ huynh | Argon2id, khóa 5 lần/15 phút, rate limit | Lưu limiter bền vững, TOTP |
| Spoofing | Đoán hoặc dùng lại mã ghép | Mã ngẫu nhiên, 10 phút, dùng một lần, rate limit | Phòng chống phân tán |
| Tampering | Sửa policy trong cache | Chưa có enforcement | Chữ ký, ACL, bảo vệ khóa |
| Repudiation | Phụ huynh phủ nhận đổi luật | Audit old/new, thời gian và IP | Chống sửa audit, child-view |
| Information disclosure | Phụ huynh A xem dữ liệu B | Kiểm tra ownership ở truy vấn, tests | Kiểm tra mọi API mới |
| Information disclosure | Đánh cắp token qua mạng/đĩa | Loopback; server chỉ lưu hash; simulator giữ RAM | TLS/pinning, DPAPI |
| Denial of service | Gửi dồn login/enroll | Rate limit một process | Giới hạn toàn hệ thống và dung lượng dữ liệu |
| Elevation of privilege | Trẻ sửa cấu hình hoặc kill service | Chưa cài service/kiểm soát | Tài khoản standard, ACL, SCM recovery, nêu giới hạn admin |
| Tampering | Trẻ lùi đồng hồ để tăng quota | Chưa có quota enforcement | Monotonic clock và đối chiếu server |
| Information disclosure | Lạm dụng thành stalkerware theo dõi người lớn | Simulator hiển thị console, không thu hoạt động | Tray bắt buộc, dừng khi UI mất, quy trình gỡ hợp pháp |

Checklist ASVS tối thiểu 20 mục theo đề sẽ bổ sung cùng bằng chứng kiểm thử;
bảng này là bản nháp STRIDE, không thay thế checklist.
