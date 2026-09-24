# Dữ liệu và mục đích sử dụng

Bản nháp cho môi trường phát triển, chỉ dùng dữ liệu giả.
Đây là mô tả hiện trạng kỹ thuật, chưa phải kết luận tuân thủ pháp lý.
Cần tự kiểm chứng văn bản gốc khi viết phần pháp lý trong báo cáo.

| Trường hoặc nhóm | Mục đích | Thời hạn hiện tại / mục tiêu | Ai truy cập |
|---|---|---|---|
| parent.id, email | Đăng nhập và xác định chủ sở hữu | Đến khi có chức năng xóa tài khoản | Phụ huynh, server |
| password_hash | Xác minh mật khẩu Argon2id | Đến khi đổi/xóa tài khoản | Server; không trả qua API |
| failed_attempts, locked_until | Chống dò mật khẩu | Reset sau đăng nhập thành công hoặc chu kỳ khóa | Server |
| session token_hash, csrf_token, parent_id, expires_at | Phiên 12 giờ, chống CSRF | Hết hiệu lực sau 12 giờ; dọn session cũ khi đăng nhập | Server; trình duyệt giữ cookie/token tương ứng |
| child.id, parent_id, display_name | Gắn thiết bị với hồ sơ trẻ | Chưa tự xóa; sẽ bổ sung xóa theo yêu cầu | Phụ huynh sở hữu, server |
| code_hash, child_id, expires_at, consent_at | Ghép đôi có đồng ý | Hạn 10 phút; xóa khi dùng hoặc thay mã | Server; mã thô chỉ trả lúc tạo |
| device.id, child_id, display_name, fingerprint hash | Định danh thiết bị demo | Chưa có chức năng xóa; cần bổ sung | Server; phụ huynh xem ID và tên |
| access_hash, refresh_hash, thời hạn, revoked | Xác thực và thu hồi thiết bị | Access 15 phút, refresh 30 ngày; bị thay khi refresh | Server; token thô chỉ giữ trong RAM simulator |
| last_seen, policy_version | Trạng thái đồng bộ | Chỉ giữ giá trị mới nhất | Phụ huynh, server |
| policy.child_id, version, quota | Cấu hình thời gian | Giữ bản hiện tại, cache tại agent | Phụ huynh, server, thiết bị tương ứng |
| audit.id, parent_id, child_id, action, ts, ip, old/new | Giải thích đồng ý ghép đôi và thay luật | Chưa tự xóa; cần chính sách retention cụ thể | Phụ huynh sở hữu, server; child-view chưa có |

Chưa ghi sự kiện sử dụng. Lược đồ sự kiện tương lai phải đúng:
ts, device_id, child_id, type, subject, duration_sec, policy_id.
Subject chỉ chứa tên ứng dụng hoặc tên miền phù hợp đề; không URL đầy đủ,
tiêu đề cửa sổ, nội dung gõ phím, tin nhắn, tài liệu hay ảnh chụp màn hình.

## Phần cần làm

- Tác vụ tự xóa dữ liệu hoạt động quá 90 ngày.
- Xóa dữ liệu theo yêu cầu trên cả server và agent, kể cả agent đang offline.
- Quyền child-view cho cùng báo cáo và audit, kèm xử lý trường IP phù hợp.
- AES-GCM cho trường nhạy cảm; phân loại dữ liệu và quản lý khóa.
- Phân biệt hết hạn sử dụng với xóa vật lý; mã/token hết hạn chưa chắc đã được dọn.
- Không gửi dữ liệu người dùng tới dịch vụ thứ ba.

## Phiên bản dành cho trẻ

Bản thử này nhớ tên gọi của em, tên máy và thời gian bố mẹ cài đặt.
Nó biết máy vừa kết nối với chương trình lúc nào.
Nó không đọc bài em viết, tin nhắn hay chụp màn hình.
Hiện chương trình chưa khóa máy và chưa xem em mở ứng dụng hay trang web nào.
