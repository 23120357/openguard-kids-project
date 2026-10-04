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
| child.id, parent_id, display_name, pin_hash | Hồ sơ và PIN trẻ do phụ huynh đặt | Chưa tự xóa; sẽ bổ sung xóa theo yêu cầu | Server giữ Argon2 hash; thiết bị cùng tài khoản phụ huynh nhận hash đã ký để xác minh local |
| code_hash, child_id, expires_at, consent_at | Ghép đôi có đồng ý | Hạn 10 phút; xóa khi dùng hoặc thay mã | Server; mã thô chỉ trả lúc tạo |
| device.id, child_id, display_name, fingerprint hash | Định danh thiết bị demo | Chưa có chức năng xóa; cần bổ sung | Server; phụ huynh xem ID và tên |
| access_hash, refresh_hash, thời hạn, revoked | Xác thực và thu hồi thiết bị | Access 15 phút, refresh 30 ngày; bị thay khi refresh | Server; token thô trên agent lưu trong thư mục ACL của service |
| last_seen, policy_version, active_child_id, active_user, active_since | Trạng thái đồng bộ và hồ sơ trẻ đang dùng máy | Hiện trạng thái gần nhất | Phụ huynh, server |
| policy.child_id, version, quota | Cấu hình thời gian theo từng trẻ | Giữ bản hiện tại, cache tại agent | Phụ huynh, server, thiết bị đã ghép cùng tài khoản phụ huynh |
| audit.id, parent_id, child_id, action, ts, ip, old/new | Giải thích ghép đôi, policy, request và quyết định cấp giờ | Chưa tự xóa; cần chính sách retention cụ thể | Phụ huynh sở hữu, server; trẻ xem qua device-scoped Tray |
| time request: requester, child_id, device, minutes, status, timestamps | Phụ huynh quyết định cấp thêm thời gian | Giữ ở server; chưa có retention job | Phụ huynh trong tài khoản hiện tại; agent gửi hồ sơ đã đăng nhập trên device |
| profiles-cache.json, failed attempts | Xác thực PIN local và dùng đúng policy theo trẻ | Cache có chữ ký HMAC trong thư mục ACL; khóa thử lại 15 phút sau 5 lần sai | Service trên máy; PIN trẻ nhập ở Tray không gửi lên server |
| ui_connected, request outbox | Hiển thị kết nối và xếp hàng request xin giờ | Chỉ trong RAM; mất khi service dừng | Service và Tray UI trên cùng máy |
| F1 local_date, used_seconds, extra_seconds, grace, warning state, recorded_at | Áp dụng quota và khoản cộng riêng theo từng hồ sơ | SQLite cục bộ cho mỗi trẻ; state giữ tới cleanup; extra_seconds hết vào ngày mới | Service; Tray chỉ đọc trạng thái của hồ sơ đang dùng |
| F1 event: warning, lock directive, clock rollback, recorded_at | Giải thích việc cảnh báo/khóa và chẩn đoán đổi giờ; ISO UTC ghi cả ngày và giờ | Cửa sổ 90 ngày được dọn khi ghi event mới | SYSTEM/Administrators; thông báo liên quan hiển thị cho trẻ |

Chưa ghi tên ứng dụng/trang web hay activity event chi tiết. Lược đồ sự kiện tương lai phải đúng:
ts, device_id, child_id, type, subject, duration_sec, policy_id.
Subject chỉ chứa tên ứng dụng hoặc tên miền phù hợp đề; không URL đầy đủ,
tiêu đề cửa sổ, nội dung gõ phím, tin nhắn, tài liệu hay ảnh chụp màn hình.

## Phần cần làm

- Tác vụ tự xóa dữ liệu hoạt động quá 90 ngày.
- Xóa dữ liệu theo yêu cầu trên cả server và agent, kể cả agent đang offline.
- Hoàn thiện child-view production cho báo cáo/audit; hiện chỉ có device-scoped
  audit tối giản và cần quyết định cách hiển thị IP cho trẻ.
- AES-GCM cho trường nhạy cảm; phân loại dữ liệu và quản lý khóa.
- Phân biệt hết hạn sử dụng với xóa vật lý; mã/token hết hạn chưa chắc đã được dọn.
- Không gửi dữ liệu người dùng tới dịch vụ thứ ba.

## Phiên bản dành cho trẻ

Bản thử này nhớ tên gọi của em, tên máy và thời gian bố mẹ cài đặt.
Nó biết máy vừa kết nối với chương trình lúc nào.
Nó không đọc bài em viết, tin nhắn hay chụp màn hình.
Chương trình có thể đếm tổng thời gian, tạm đếm khi em nghỉ quá 5 phút hoặc khóa
màn hình, và khóa Windows theo quota/lịch. Nó không xem em mở ứng dụng hay trang web nào.
Nút xin thêm giờ gửi tên hồ sơ đang đăng nhập, tên máy, số phút và thời gian gửi
đến dashboard của phụ huynh. PIN do phụ huynh tạo đi tới server một lần để băm
Argon2; sau đó service nhận hash đã ký và xác minh cục bộ. PIN em nhập ở Tray không
gửi lên server.
