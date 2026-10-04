# Kịch bản demo cuối Tuần 2

Chuẩn bị máy Windows lab, lưu mọi công việc trước khi thử chức năng khóa.

1. Khởi động server theo `README.md`, đăng nhập dashboard.
2. Tạo hồ sơ trẻ với username/PIN, tạo mã ghép đôi.
3. Chạy `& .\scripts\Setup-OGKAgent.ps1`, nhập mã và đăng nhập trẻ trên Tray.
4. Cho thấy dashboard nhận thiết bị, người đang dùng, usage và remaining realtime.
5. Đổi quota cùng lịch 24h; thử một giờ sai để minh họa validation đỏ, sau đó lưu
   giờ hợp lệ và cho thấy policy/audit xuất hiện ở Tray.
6. Gửi request xin thêm giờ từ Tray, duyệt rồi từ chối một request khác trên dashboard.
7. Cộng phút trực tiếp và chứng minh usage không reset, command không áp dụng hai lần.
8. Trên máy lab, dùng quota 3 phút hoặc block slot hiện tại để demo grace và khóa.
9. Restart service, đăng nhập lại, xác nhận enrollment/cache/usage vẫn còn.
10. Chạy test tự động và chụp kết quả `140 passed`.

Cleanup server/client theo [WEEK3_HANDOFF.md](../docs/WEEK3_HANDOFF.md#5-cleanup).
Video chính thức 5-7 phút vẫn thuộc mốc Tuần 4; Tuần 3 nên quay bản nháp sau khi
F2/F3 chạy đầu-cuối.
