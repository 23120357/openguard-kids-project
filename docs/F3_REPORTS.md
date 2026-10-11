# F3: ghi nhận và báo cáo hoạt động

Đối chiếu F3 trang 7-8 của QuanLyMayTinhTreEm.pdf. Phạm vi này hoàn thiện F3,
không bao gồm các hạng mục F2 còn lại như SafeSearch/phân loại/DoH.

| Yêu cầu | Triển khai | Kiểm chứng |
|---|---|---|
| Payload đúng bảy trường, chín loại sự kiện | EventQueue và ActivityPayload; tên executable/tên miền cấp đăng ký | test_activity_events.py, test_f3_reports.py |
| Dashboard ngày/tuần, top 10, số chặn, yêu cầu | Tab Báo cáo; biểu đồ PNG xanh lá dựng bằng Pillow, hover tên ngày/tuần, tải lại mỗi 5 phút hoặc khi đổi bộ lọc; API activity-report, chung bộ tổng hợp common/activity_reports.py | Test ngày/tuần, retry, nhiều thiết bị, trình duyệt |
| Hôm nay em đã dùng gì | Tray Hôm nay: minh họa máy/web, thời gian sử dụng và số lượt hỏi địa chỉ web; snapshot báo cáo server | Test Tk bố cục/cuộn, báo cáo cùng phụ huynh |
| Top 10 ứng dụng trên Tray | Thẻ riêng dưới thống kê Hôm nay; thanh Canvas như giao diện Tray cũ, chọn 1/7/90 ngày; dùng dữ liệu đúng hồ sơ từ server khi đã đồng bộ, dữ liệu cục bộ khi ngoại tuyến | Test Tk và bộ tổng hợp |
| Retention 90 ngày và xóa cả server/agent | Job server mỗi giờ, agent vòng 5 giây kể cả offline; generation/ACK; xóa cả lịch sử F1 và request liên quan | Test retention, erasure, reconnect; giữ state quota |
| PRIVACY.md từng trường, mục đích, hạn, người xem | Bảng bảy trường và metadata/cache/export | Kiểm tra nội dung |
| Xuất báo cáo tuần PDF hoặc CSV (nên có) | Nút tải PDF có biểu đồ và số liệu tuần; API CSV UTF-8 BOM vẫn khả dụng | Test PDF/CSV, quyền sở hữu, tải tệp trình duyệt |
| Gợi ý 20-20-20 (có thì tốt) | Popup Windows sau mỗi 20 phút dùng máy cục bộ: nhìn xa 6 mét trong 20 giây | Kiểm tra UI và ngưỡng |

## Cách đo và phạm vi

- Payload F3 vẫn đúng `ts, device_id, child_id, type, subject, duration_sec,
  policy_id`. UUID/generation và lời giải thích là metadata bao ngoài theo yêu
  cầu trước đó của người dùng. Không thêm URL, query string, đường dẫn, PID,
  hash, tiêu đề cửa sổ hoặc nội dung vào sự kiện.
- Tổng thời gian máy dùng các đoạn `app_stop` của phiên ứng dụng nội bộ
  `OpenGuard Kids - Phiên máy tính`. Mỗi heartbeat đóng đoạn ngắn bằng đồng hồ
  monotonic; chỉ tính khi Tray hiện diện, trẻ đăng nhập, máy không khóa và không
  idle quá ngưỡng (mặc định 5 phút). Khoảng heartbeat gián đoạn trên 5 giây không
  tính. Đo độc lập với quota, không cộng trùng các ứng dụng chạy cùng lúc.
- App Controller ghi khởi động và đóng các đoạn chạy của executable mỗi lần
  quét, kể cả ứng dụng chưa thoát, nên ứng dụng chạy lâu vẫn có báo cáo hôm nay.
  Chỉ theo dõi phiên Windows tương ứng Tray, bỏ qua các tiến trình hệ thống
  được bảo vệ. Thời gian chạy có thể gồm nền; không tuyên bố là thời gian chú ý
  của trẻ. Các đoạn ngắn gần lúc dừng/chuyển hồ sơ có thể chưa được ghi.
- DNS proxy ghi `domain_query` cả khi luật lọc tắt; gộp A/AAAA/retry cho cùng
  trẻ và miền đăng ký trong 5 giây. Top tên miền là số lượt truy vấn đã gộp,
  không phải thời lượng đọc hay số lần mở trang. DNS nền, cache và DoH có thể
  làm số liệu khác hành vi trình duyệt; không thu thập nội dung để suy đoán.
- Tray làm mới biểu đồ tên miền và ứng dụng tối đa một lần mỗi phút. Báo cáo
  web lấy số liệu mới mỗi phút, chỉ dựng lại ảnh và danh sách khi dữ liệu đổi.
  Agent vẫn gửi sự kiện trong hàng đợi theo nhịp 5 giây; nếu offline, số liệu
  cục bộ trên Tray sẽ xuất hiện trên web sau khi kết nối và đồng bộ trở lại.
- `quota_warning`/`locked` của F1 được sao vào outbox; locked là yêu cầu khóa
  theo chính sách. Lệnh khóa từ xa ghi khi Tray xác nhận yêu cầu khóa Windows.
  `unlock_request` ghi khi xin giờ; `override_granted` ghi khi áp dụng cộng giờ,
  dùng cùng cơ chế idempotency lệnh đang có.
- Báo cáo dùng giờ Việt Nam UTC+7, chia các đoạn qua nửa đêm và qua đầu tuần.
  Ngày trống hiện 0. Biểu đồ ngày luôn có 7 cột ngày; biểu đồ tuần luôn có
  8 cột, mỗi cột gom 7 ngày liên tiếp. Cả hai có tổng thời gian và trục Y theo
  giờ. Bộ chọn 7/28/90 ngày áp dụng cho thống kê khác; top 10 ứng dụng chọn
  riêng 1/7/90 ngày. PDF dùng tuần hiện tại.
- Trẻ thấy báo cáo từ tất cả thiết bị cùng hồ sơ sau đồng bộ; snapshot chỉ RAM,
  tối đa 15 giây. Offline dùng dữ liệu máy này và ghi rõ nguồn. Không hiển thị
  báo cáo của trẻ khác trong Tray khi đổi hồ sơ.
- Xóa F3 gồm sự kiện, báo cáo dẫn xuất, yêu cầu xin giờ và audit quyết định xin
  giờ, lịch sử sự kiện F1 cục bộ và bộ đệm request trong agent. State quota,
  PIN, tài khoản, luật và audit cấu hình F4 giữ nguyên để việc xóa lịch sử không
  vượt chính sách. Agent offline xác nhận sau reconnect; snapshot báo cáo cũ
  được bỏ. Bản PDF đã tải nằm ngoài tác vụ xóa của hệ thống.

## API bổ sung

| API | Quyền | Kết quả |
|---|---|---|
| GET /api/children/{child_id}/activity-report?days=28&end_date=YYYY-MM-DD | Phụ huynh sở hữu | daily, weekly, top_apps, top_domains, total_duration_sec, blocked_count, requests |
| GET /api/children/{child_id}/activity-report/chart.png?kind=daily\|weekly\|apps&days=7 | Phụ huynh sở hữu | Ảnh PNG dựng bằng Pillow; ngày cố định 7 ngày, tuần cố định 56 ngày, `days` chỉ áp dụng cho apps; không cache |
| GET /api/children/{child_id}/activity-report.csv?week_start=YYYY-MM-DD | Phụ huynh sở hữu | Tải CSV tuần chứa ngày được chọn, mặc định tuần hiện tại |
| GET /api/children/{child_id}/activity-report.pdf?week_start=YYYY-MM-DD | Phụ huynh sở hữu | Tải PDF tuần chứa ngày được chọn, mặc định tuần hiện tại |
| GET /api/device/activity-report?child_id=...&days=1\|7\|90 | Thiết bị cùng household | Báo cáo theo hồ sơ và khoảng ngày + generation; service đưa dữ liệu 1/7/90 ngày tới Tray |

Các API từ chối phiên/token hết hạn, thiết bị đã thu hồi, truy cập chéo tài khoản.
Endpoint CSV không lưu tệp trên server, không cache. Việc ghi/xóa vẫn kiểm tra
CSRF; báo cáo chỉ đọc dữ liệu còn trong cửa sổ retention.

## Kiểm tra trên máy lab

1. Khởi động lại server, service và Tray bằng quy trình cài hiện có; Ctrl+F5 web.
2. Đăng nhập trẻ, dùng một ứng dụng lab vài phút. Tray Hôm nay phải có thời gian
   còn lại, nút xin giờ, thời gian sử dụng và số lượt web; tab Báo cáo của phụ
   huynh hiển thị 7 cột ngày, 8 cột tuần và rê chuột lên cột để xem số liệu. Top ứng dụng chọn riêng
   1 ngày/1 tuần/toàn thời gian. Sau 20 phút dùng máy, kiểm tra thông báo Windows
   nhắc nghỉ mắt giống thông báo sắp hết giờ.
3. Để kiểm tra Top 10 tên miền mà không đổi DNS toàn máy, giữ Tray đang chạy và
   đăng nhập trẻ, rồi chạy `Resolve-DnsName -Name example.test -Server 127.0.0.1
   -Type A -DnsOnly` trong PowerShell. Nếu `example.test` nằm trong danh sách
   chặn, lệnh báo không tìm thấy địa chỉ nhưng lượt hỏi vẫn được ghi. Chờ ít
   nhất 6 giây rồi chạy lại 2 lần; Tray Hôm nay phải hiển thị `example.test`
   với khoảng 3 lượt hỏi. Đổi tên thành `another.test` để có dòng thứ hai.
   Sau khi agent đồng bộ, chọn đúng hồ sơ trẻ và chờ tối đa một phút để xem
   Top 10 tên miền trong tab Báo cáo; khoảng báo cáo phải bao gồm hôm nay.
   Tray ghi rõ khi còn dùng dữ liệu cục bộ. Cùng một miền bị chặn chỉ mở một hộp thoại lý do trong phiên;
   các lượt hỏi vẫn được đếm.
4. Xin thêm giờ và duyệt từ dashboard. Kiểm tra danh sách yêu cầu, thông báo
   được cộng giờ và sự kiện F3. Chặn/rút quota chỉ thử trên máy lab.
5. Xuất PDF tuần; mở tệp và đối chiếu biểu đồ, thời lượng, ứng dụng, tên miền, yêu cầu.
6. Tắt server: Tray ghi rõ báo cáo cục bộ; bật server: đồng bộ không nhân đôi
   dữ liệu. Đổi hồ sơ không được giữ số liệu trẻ trước.
7. Xóa hoạt động khi agent offline: Dashboard về 0, có trạng thái chờ ACK;
   reconnect: lịch sử/outbox/request cục bộ bị xóa, báo cáo về 0, quota không reset.

Kiểm thử tự động xác minh mã và luồng mô phỏng. Nghiệm thu service, ứng dụng thật,
DNS adapter và khóa Windows trên máy lab vẫn cần thực hiện các bước trên.
