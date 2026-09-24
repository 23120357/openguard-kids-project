# Bàn giao tuần 1

Bộ khung hiện đã có phần nền server và simulator để người tiếp theo tích hợp.
Chưa được xem là đã hoàn thành toàn bộ tuần 1 theo đề.

## Người làm trước

- [x] Cấu trúc dự án, cấu hình môi trường và tài khoản seed
- [x] Database và quan hệ phụ huynh–trẻ–thiết bị
- [x] Login, CSRF, enrollment, heartbeat, policy
- [x] Dashboard tối thiểu và simulator kiểm thử đầu–cuối
- [x] README, mô tả API và bản nháp PRIVACY
- [ ] Tự chạy lại toàn bộ demo trên máy thứ hai
- [ ] Commit/tag mốc bàn giao sau khi cả hai thống nhất

## Người tiếp tục

1. Clone repository, cài theo README, chạy tests và demo.
2. Đọc agent/simulator.py và docs/API.md; giữ hợp đồng API khi thay simulator
   bằng agent thật. Nếu phải đổi thì sửa server, docs và tests cùng lúc.
3. Làm Tray UI luôn hiển thị, thông báo khởi động và màn hình minh bạch cho trẻ.
4. Dựng thử Windows Service bằng pywin32; chọn named pipe có ACL cho Service–Tray.
   Thử hành vi service khi UI tắt; chưa thêm theo dõi trước khi cơ chế này hoạt động.
5. Lưu định danh/token bằng DPAPI, cache vào ProgramData với ACL; khởi động lại
   không tạo thiết bị mới. Kiểm thử refresh/recovery khi response bị mất.
6. Chuyển HTTP lab sang TLS, thiết kế pinning và ký policy trước khi enforcement.
7. Bổ sung Alembic migration và thỏa thuận định dạng policy cho tuần 2.

## Kịch bản nghiệm thu có thể làm ngay

- Login sai bị từ chối; phụ huynh B không đọc/sửa hồ sơ của A.
- Ghép đôi một lần thành công; tái sử dụng mã thất bại.
- Heartbeat làm thiết bị online, dừng agent quá 120 giây chuyển offline.
- Đổi quota làm version tăng, agent lưu policy mới trong một chu kỳ heartbeat.
- Ngắt server, simulator giữ cache; bật lại và quan sát kết nối phục hồi.
- Khởi động lại chương trình với --show-cache vẫn đọc được cache.
- Logout rồi gửi lại cookie cũ phải nhận 401.

## Các tuần sau

| Tuần | Công việc chính |
|---|---|
| 2 | Monotonic counter, idle/lock, quota, lịch 7×48, cảnh báo và ân hạn; WebSocket commands |
| 3 | DNS proxy, kiểm soát ứng dụng SHA-256, phân loại miền, SafeSearch, event queue, báo cáo và yêu cầu của trẻ |
| 4 | Hoàn thiện bảo mật, retention/xóa dữ liệu, bypass, đo M1–M6, báo cáo, video và cài máy sạch |

Mỗi thành viên phải hiểu luồng đầu–cuối để vấn đáp; cập nhật phân công thực tế
và AI_USAGE khi tiếp tục sử dụng hỗ trợ AI.
