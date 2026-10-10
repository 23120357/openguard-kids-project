# Khai báo hỗ trợ AI

## Lần dựng bộ khung ban đầu

- Công cụ: OpenAI Codex.
- Phạm vi: cấu trúc dự án, server FastAPI, dashboard, simulator, tests và tài liệu.
- AI có đọc tài liệu đề bài QuanLyMayTinhTreEm.docx trong workspace.
- Kiểm chứng tự động: pytest, Ruff và kiểm tra cú pháp JavaScript.
- Nhóm cần tự kiểm chứng: demo trên Windows sạch, kỹ thuật Windows, yêu cầu
  pháp lý, hiệu năng, đường vòng, chức năng bảo mật hoàn chỉnh và UI cho trẻ.
- Không có số đo thực nghiệm DNS/quota/CPU/RAM nào được tạo trong bộ khung này.
- Nhóm cần cập nhật kết quả kiểm chứng và đóng góp thực tế trước khi nộp bài.

## Phát triển Tuần 2 và bàn giao Tuần 3

- Công cụ: OpenAI Codex trong môi trường repository cục bộ.
- Phạm vi hỗ trợ: Windows Service/Tray, named pipe, F1 state machine, F4 remote
  sync, dashboard realtime, profile PIN, request xin giờ, test, tài liệu và slide
  tiến độ `OpenGuardKids_Tuan1_den_Tuan2.pptx`.
- Kiểm chứng đã chạy: 140 test pytest, Ruff, kiểm tra cú pháp JavaScript, smoke test
  named pipe/server và render slide tự động.
- Các trạng thái “đã triển khai” trong tài liệu dựa trên mã/test. Các trạng thái
  “cần acceptance” không được nâng thành hoàn thành chỉ từ test mô phỏng.
- Nhóm vẫn phải tự chạy khóa Windows thật, đo latency đầu-cuối, sai số một giờ,
  thử trên máy sạch và chịu trách nhiệm về trích dẫn pháp lý trước khi nộp.
## Phát triển sự kiện Tuần 3

- OpenAI Codex hỗ trợ thiết kế và triển khai event outbox, ingestion chống trùng,
  deletion generation, retention 90 ngày cho sự kiện F3, popup/Tray/dashboard,
  kiểm soát executable SHA-256 và DNS proxy cơ bản.
- Mã và test được viết theo yêu cầu bổ sung của người dùng về popup và tab Sự kiện;
  `explanation` là mở rộng có mục đích ngoài payload bảy trường F3.
- Kiểm thử tự động không thay thế nghiệm thu service/Tray/Windows DNS trên máy
  lab sạch. Không tự thay DNS hoặc chạy kết thúc ứng dụng trên máy người dùng.

## Cập nhật giao diện phụ huynh và cuộn sự kiện

- Codex hỗ trợ tách web phụ huynh thành bốn tab: Dashboard, Chính sách thời gian,
  Quản lí web & ứng dụng, Sự kiện. Danh sách tên miền có từng dòng thêm/sửa/xóa;
  thay đổi áp dụng khi lưu quy tắc, và giữ bản nháp khi dữ liệu tự làm mới.
- Tray hỗ trợ cuộn chuột trong tab Sự kiện và giữ vị trí cuộn khi nhận cập nhật.
- Kiểm thử trình duyệt dùng API mô phỏng để kiểm tra đăng nhập/đăng xuất, chuyển
  tab, đổi hồ sơ, lưu chính sách/quy tắc, sự kiện, lệnh khóa, ghép đôi, bàn phím
  và bố cục di động. API server được kiểm tra riêng bằng pytest.
