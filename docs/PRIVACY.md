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
| time request: requester, child_id, device, minutes, status, timestamps | Phụ huynh quyết định cấp thêm thời gian và trẻ xem kết quả | 90 ngày; tự dọn mỗi giờ ở server; xóa cùng dữ liệu hoạt động | Phụ huynh sở hữu; trẻ xem hồ sơ đang đăng nhập |
| profiles-cache.json, failed attempts | Xác thực PIN local và dùng đúng policy theo trẻ | Cache có chữ ký HMAC trong thư mục ACL; khóa thử lại 15 phút sau 5 lần sai | Service trên máy; PIN trẻ nhập ở Tray không gửi lên server |
| ui_connected, request outbox | Hiển thị kết nối và xếp hàng request xin giờ | Chỉ trong RAM; mất khi service dừng | Service và Tray UI trên cùng máy |
| F1 local_date, used_seconds, extra_seconds, grace, warning state, recorded_at | Áp dụng quota và khoản cộng riêng theo từng hồ sơ | SQLite cục bộ cho mỗi trẻ; state giữ tới cleanup; extra_seconds hết vào ngày mới | Service; Tray chỉ đọc trạng thái của hồ sơ đang dùng |
| F1 event: warning, lock directive, clock rollback, recorded_at | Giải thích việc cảnh báo/khóa và chẩn đoán đổi giờ; ISO UTC ghi cả ngày và giờ | 90 ngày; agent đã ghép đôi dọn mỗi vòng đồng bộ kể cả offline; xóa lịch sử cùng F3, giữ state thực thi quota | SYSTEM/Administrators; thông báo liên quan hiển thị cho trẻ |

## Sự kiện F3 triển khai Tuần 3

| Trường hoặc nhóm | Mục đích | Thời hạn | Ai truy cập |
|---|---|---|---|
| ts | Xác định ngày/tuần và thứ tự hoạt động, không chứa nội dung | 90 ngày hoặc xóa theo yêu cầu | Service/server; phụ huynh sở hữu; trẻ đang đăng nhập |
| device_id | Chống trùng và cộng báo cáo từ các thiết bị của cùng trẻ | 90 ngày hoặc xóa theo yêu cầu | Cùng quyền xem sự kiện |
| child_id | Gắn hoạt động với đúng hồ sơ, kiểm tra quyền xem/xóa | 90 ngày hoặc xóa theo yêu cầu | Cùng quyền xem sự kiện |
| type | Phân biệt mở/đóng ứng dụng, truy vấn/chặn, cảnh báo, khóa, xin/cấp giờ | 90 ngày hoặc xóa theo yêu cầu | Cùng quyền xem sự kiện |
| subject | Tên ứng dụng hoặc tên miền cấp đăng ký để lập top 10; tên phiên OpenGuard Kids dùng tính tổng thời gian máy | 90 ngày hoặc xóa theo yêu cầu | Cùng quyền xem sự kiện |
| duration_sec | Độ dài đoạn chạy ứng dụng/đoạn dùng máy, ghép thành biểu đồ ngày/tuần | 90 ngày hoặc xóa theo yêu cầu | Cùng quyền xem sự kiện |
| policy_id | Giải thích phiên bản luật thời gian/lọc hoặc lệnh phụ huynh liên quan | 90 ngày hoặc xóa theo yêu cầu | Cùng quyền xem sự kiện |
| explanation.reason, rule_author | Hiển thị cùng lý do/người đặt luật tại thời điểm chặn trên popup và lịch sử hai phía | Cùng sự kiện: 90 ngày hoặc xóa theo yêu cầu | Cùng quyền xem sự kiện |
| UUID, generation, sent, notified | Chống trùng, trạng thái gửi/thông báo của sự kiện | Cùng thời hạn sự kiện | Service/server; UUID chỉ để đồng bộ |
| generation/ACK theo trẻ và thiết bị | Ngăn agent offline gửi lại sự kiện đã xóa; báo trạng thái xóa | Giữ trong vòng đời hồ sơ/thiết bị; không chứa hoạt động truy cập | Service/server; phụ huynh xem trạng thái |
| filtering rules: tên ứng dụng và SHA-256, tên miền và danh sách miễn chặn | Nhận diện executable và áp dụng luật do phụ huynh đặt | Chính sách hiện tại, bản cache có HMAC tại agent | Phụ huynh sở hữu, service/server |
| Báo cáo ngày/tuần, top 10, số lần chặn | Tổng hợp từ sự kiện và yêu cầu, cùng cách tính trên server/agent | Không tạo bảng lưu riêng; snapshot Tray chỉ RAM, hết mới sau 15 giây; cùng hạn 90 ngày của nguồn | Phụ huynh sở hữu; Tray chỉ báo cáo trẻ đang đăng nhập |
| CSV tuần tải về | Phụ huynh lưu/in báo cáo tuần theo yêu cầu | Hệ thống không lưu bản CSV; bản đã tải do phụ huynh tự quản lý, nằm ngoài tác vụ xóa | Phụ huynh tải và người được họ chia sẻ |

Đã ghi activity event tối thiểu. Payload sự kiện gồm:
ts, device_id, child_id, type, subject, duration_sec, policy_id.
Subject chỉ chứa tên ứng dụng hoặc tên miền phù hợp đề; không URL đầy đủ,
tiêu đề cửa sổ, nội dung gõ phím, tin nhắn, tài liệu hay ảnh chụp màn hình.

## Phần cần làm

- Retention/xóa sự kiện F3 đã triển khai đầy đủ, gồm hàng rào xóa cho agent offline;
  xem WEEK3_EVENTS.md. Các bảng tài khoản, audit/request Tuần 2 và state thực thi
  quota vẫn có vòng đời riêng như bảng trên; chức năng mới không xóa tài khoản.
- Báo cáo F3/child-view đã có; audit F4 vẫn tối giản và cần quyết định cách hiển thị IP cho trẻ.
- AES-GCM cho trường nhạy cảm; phân loại dữ liệu và quản lý khóa.
- Phân biệt hết hạn sử dụng với xóa vật lý; mã/token hết hạn chưa chắc đã được dọn.
- Không gửi dữ liệu người dùng tới dịch vụ thứ ba.

## Phiên bản dành cho trẻ

Bản thử này nhớ tên gọi của em, tên máy và thời gian bố mẹ cài đặt.
Nó biết máy vừa kết nối với chương trình lúc nào.
Nó không đọc bài em viết, tin nhắn hay chụp màn hình.
Chương trình có thể đếm tổng thời gian, tạm đếm khi em nghỉ quá 5 phút hoặc khóa
màn hình, và khóa Windows theo quota/lịch. Nó ghi tên ứng dụng chạy trong phiên Windows của em và tên miền máy hỏi qua DNS proxy, kể cả khi luật chặn tắt. Nó không ghi URL đầy đủ hoặc nội dung trang. Trong tab Hôm nay, em xem thời gian dùng máy, ứng dụng, tên miền và yêu cầu của mình. Khi đồng bộ, em thấy cùng dữ liệu từ các máy như bố mẹ; khi ngoại tuyến, màn hình ghi rõ chỉ có dữ liệu máy này.
Nút xin thêm giờ gửi tên hồ sơ đang đăng nhập, tên máy, số phút và thời gian gửi
đến dashboard của phụ huynh. PIN do phụ huynh tạo đi tới server một lần để băm
Argon2; sau đó service nhận hash đã ký và xác minh cục bộ. PIN em nhập ở Tray không
gửi lên server.
