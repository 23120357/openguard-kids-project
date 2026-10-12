# F2 kiểm soát ứng dụng và website

**Cập nhật tích hợp trình duyệt:** service đã tự cấu hình DNS IPv4/IPv6 và policy
Secure DNS, có lưu/khôi phục cấu hình. Xem [WEB_PROTECTION.md](WEB_PROTECTION.md).
Các bước đặt DNS thủ công dưới đây là quy trình nghiệm thu cũ; với service mới
dùng quy trình trong tài liệu trên. Chưa nghiệm thu cấu hình mới trên máy thật.

## Phạm vi triển khai

- App allowlist/blocklist đối chiếu SHA-256; tên trong luật để nhận biết. Đổi tên
  executable không thay đổi quyết định chặn. Tên tiến trình hệ thống chỉ được miễn
  trong vị trí Windows tin cậy, sau khi resolve đường dẫn. Cần tài khoản trẻ là
  standard user và giữ ACL thư mục Windows; đây không phải xác minh Authenticode.
- Kết thúc tiến trình bị chặn, ghi sự kiện và hiển thị lý do qua Tray hiện có.
- DNS proxy tại 127.0.0.1:53, UDP/TCP, áp dụng cả tên miền con.
- Phân loại offline: `common/domain_categories.csv`; tra tên miền cụ thể nhất trước,
  miền không có trong bảng nhận nhóm `unclassified`.
- Sáu nhóm và mặc định 6–11 tuổi đã được người dùng chọn: cho phép giáo dục,
  giải trí, chưa phân loại; chặn mạng xã hội, trò chơi, không phù hợp lứa tuổi.
  Phụ huynh thay đổi từng nhóm trên dashboard. Tắt kiểm soát sẽ tắt cả phân loại
  và cưỡng chế SafeSearch.
- Thứ tự ưu tiên: miền hỗ trợ/trường học miễn chặn → blocklist riêng → giới hạn
  allowlist nếu bật → allowlist riêng → hành động theo nhóm. Sau khi được phép,
  miền tìm kiếm vẫn áp dụng SafeSearch; allowlist không tắt SafeSearch.
- Google chuyển sang `forcesafesearch.google.com`, Bing sang `strict.bing.com`.
  Xử lý A/AAAA/CNAME, không chuyển tiếp HTTPS/SVCB của hostname gốc. Lỗi upstream
  trả SERVFAIL, không quay về tìm kiếm thường. Host được hỗ trợ nằm trong
  `SAFE_SEARCH_HOSTS`: Google com/com.vn/co.uk/com.au/ca/fr/de/co.jp/co.in
  (có và không www); Bing bing.com/www.bing.com/edgeservices.bing.com.
- Schema mới được áp dụng khi đọc chính sách cũ, không cần thay đổi bảng SQLite.
  Chính sách gửi agent vẫn được ký HMAC và có phiên bản; audit lưu cả giá trị mới.

## Bảng phân loại

Phụ huynh có thể thêm/sửa tên miền, chuyển nhóm và xóa phân loại riêng ngay
trên dashboard, kèm tìm kiếm và nhãn Mặc định/Tùy chỉnh/Tự thêm. Các thay đổi
nằm trong `category_overrides` của hồ sơ trẻ, tối đa 200 miền; lưu cùng phiên
bản, audit và chữ ký của chính sách. Không sửa CSV chung hoặc hồ sơ trẻ khác.
Xóa tùy chỉnh trả về phân loại mặc định tại miền đó, nếu không có thì tra miền
cha rồi mới về Chưa phân loại. Tra hostname cụ thể nhất trước; tại cùng hostname,
phân loại riêng ưu tiên hơn CSV. Muốn bỏ một miền mặc định khỏi nhóm, chuyển
miền đó sang nhóm Chưa phân loại; nút Về mặc định xóa tùy chỉnh này.
Các danh sách luôn cho phép/chặn riêng vẫn ưu tiên hơn phân loại nhóm.

Dashboard có “Xem website trong nhóm” dưới từng nhóm, hiển thị số mục và danh
sách cuộn. Ô “Kiểm tra tên miền” nhận tên miền/URL nhưng chỉ gửi hostname tới
server; trả về nhóm, cho phép/chặn và lý do theo biểu mẫu đang chỉnh (kể cả
thay đổi chưa lưu). Dùng cùng logic quyết định với agent, không ghi chính sách
hay lịch sử truy cập. Kết quả bị xóa khi đổi luật hoặc hồ sơ để tránh hiển thị
quyết định cũ; cần lưu chính sách và đồng bộ agent để áp dụng thực tế.

Bảng có 311 mục miền/subdomain thật và một fixture `.test`. Cột `source` là
địa chỉ trang chủ để người rà soát kiểm tra; không phải chứng nhận rằng nội dung
đã được kiểm duyệt. Các mục thật có `review_status=seed_manual_review_required`:
đây là bảng seed phân loại theo mục đích phổ biến của dịch vụ/tổ chức, chưa kiểm
duyệt từng website trực tiếp. Một tổ chức giáo dục vẫn có thể có nội dung không
phù hợp với từng lứa tuổi. Không được diễn giải nhóm giáo dục là bảo đảm an toàn.

Nhóm không phù hợp lứa tuổi dùng `age-restricted.example.test` để kiểm thử an
toàn, không tính vào 311 mục thật. Không có miền nội dung người lớn trong bộ nộp.
Trước nghiệm thu, rà soát bảng và cập nhật review_status; có thể thêm miền theo
quyết định của phụ huynh mà không cần thu thập nội dung duyệt web. Bảng là dữ liệu
đi kèm bản phát hành, cần phân phối cùng `common/` khi cài agent.

## Kiểm thử tự động

```powershell
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pytest tests/test_f2_filtering.py tests/test_activity_events.py tests/test_f3_reports.py tests/test_tray_ui.py -q
.venv/Scripts/python.exe -m scripts.check_f2_dns --output output/f2-dns.json
```

Script mặc định chạy proxy và upstream mô phỏng trên loopback/cổng riêng;
không thay đổi DNS adapter, không truy cập website thật, không đổi policy đang
dùng. Bộ `tests/assets/f2_dns_cases.csv` chứa 50 miền công khai trung tính được
chặn có chủ đích bằng blocklist lab và 20 miền giáo dục không được miễn chặn.
Mỗi miền thử A và AAAA trên UDP và TCP; miền chặn thử cả hostname gốc và www.
Một miền chỉ đạt khi mọi truy vấn của nó đạt. Mục tiêu ≥48/50 miền bị chặn,
20/20 miền giáo dục được phép. Timeout/SERVFAIL/NXDOMAIN ở miền giáo dục đều
làm bài đo thất bại, không được ghi nhận nhầm là cho phép.

JSON kết quả có `mode=isolated`, số liệu và từng truy vấn. File `.policy.json`
kèm theo là policy lab tham khảo; script không tự áp dụng nó. Đây là đo cơ chế
DNS và thứ tự luật, không phải đo độ chính xác phân loại nội dung hay Internet thật.

## Nghiệm thu Windows thật

1. Dùng máy lab, trẻ là standard user. Cài dependency, khởi động lại server,
   service và Tray, đăng nhập trẻ, tải lại dashboard. Bật kiểm soát và kiểm tra
   đủ 6 nhóm + SafeSearch; lưu rồi tải lại phải giữ đúng giá trị.
2. Dùng một executable lab không có dữ liệu cần lưu. Lấy hash bằng
   `python -m agent.filtering C:\Lab\sample.exe`, thêm vào danh sách chặn.
   Chạy bản sao tên `game.exe`, rồi bản sao tên `explorer.exe` trong thư mục lab:
   phải bị kết thúc, có popup lý do, có lịch sử chặn. Không đổi tên/tắt executable
   Windows thật. Kiểm tra ứng dụng được phép vẫn chạy.
3. Ghi lại DNS adapter IPv4/IPv6 trước khi thay đổi. Cấu hình DNS lab qua
   127.0.0.1, không để DNS phụ tạo đường vòng; tắt Secure DNS/DoH riêng của trình
   duyệt trong lượt nghiệm thu cơ bản. Kiểm tra port 53 không bị dịch vụ khác chiếm.
4. Áp dụng blocklist 50 miền trong file policy lab lên hồ sơ lab, giữ 20 miền
   giáo dục không có trong safety_domains; chạy:

   ```powershell
   .venv/Scripts/python.exe -m scripts.check_f2_dns --live --output output/f2-dns-live.json
   ```

   Đo này truy vấn DNS, không mở trang. Nếu website thật không có AAAA, bài đo
   live nghiêm ngặt có thể không đạt mục giáo dục dù bộ lọc không chặn; lưu kết
   quả thô và phân biệt thiếu bản ghi với chặn nhầm, không sửa kết quả để đạt.
5. Dùng policy bình thường cho phép Google/Bing. Xóa DNS cache bằng
   `Clear-DnsClientCache`, đóng/mở lại trình duyệt rồi kiểm tra:

   ```powershell
   nslookup -type=A www.google.com 127.0.0.1
   nslookup -type=AAAA www.google.com.vn 127.0.0.1
   nslookup -type=CNAME www.bing.com 127.0.0.1
   ```

   Kết quả phải có alias forcesafesearch/strict; mở Google SafeSearch và Bing
   settings để xác nhận bị cưỡng chế. Chụp kết quả DNS và giao diện cài đặt;
   không tìm nội dung người lớn để thử.
6. Bật DoH hoặc đổi DNS sang 8.8.8.8 trong lượt kiểm tra giới hạn riêng và ghi
   nhận khả năng vượt bộ lọc. Khôi phục DNS và policy ban đầu sau thử nghiệm.

## Giới hạn còn lại

Kết quả kiểm tra ngày 11/10/2026: 108 test F2/activity/F3/Tray đạt; kiểm thử
dashboard headless trên Edge đạt, gồm lưu/tải lại category_actions, SafeSearch
và chuyển hồ sơ. Bộ đo DNS isolated đạt 50/50 miền chặn, 20/20 miền giáo dục,
480 truy vấn qua UDP/TCP. Kết quả lưu ở `output/f2-dns.json`; ảnh dashboard ở
`output/f2-dashboard.png`. Không thay đổi DNS adapter hoặc policy đang dùng.

Chưa triển khai chặn DoH/canary, khóa cấu hình DNS/chuyển hướng cổng 53 hoặc WFP.
DoH/DoT, VPN, DNS cache, IP trực tiếp, Google hostname ngoài danh sách vẫn cần
xử lý riêng. Chỉ lọc khi có hồ sơ trẻ và Tray heartbeat; đây chưa phải cơ chế
chống can thiệp hoàn chỉnh. Không tuyên bố đã nghiệm thu Windows thật từ các
test mô phỏng. Dataset seed cần người rà soát trước khi tuyên bố phân loại đạt.

## Nguồn SafeSearch

- Google: https://support.google.com/websearch/answer/186669
- Microsoft: https://learn.microsoft.com/en-us/microsoftsearch/retirement-microsoft-search-bing

Triển khai DNS không đọc URL, query string hoặc nội dung trang và không bổ sung
trường nhạy cảm vào payload F3.
