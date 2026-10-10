# Tuần 3: kiểm soát ứng dụng, sự kiện chặn và retention

## Phạm vi đã triển khai

- Popup trong phiên tương tác của trẻ khi chặn ứng dụng hoặc tên miền: tên,
  lý do, người đặt luật. Popup do Tray tạo, không chạy giao diện dưới SYSTEM.
- Tab **Sự kiện** trong Tray: tối đa 30 lần chặn gần nhất của hồ sơ đang đăng nhập
  (giảm số dòng nếu lời giải thích dài để giữ giới hạn IPC 64 KiB).
  Dashboard có tab cùng tên, cùng dữ liệu/lý do, phân trang 50 mục và chọn hồ sơ.
- App Controller kiểm tra tệp thực thi bằng SHA-256, nhận diện được khi đổi tên;
  chỉ kết thúc ứng dụng trong phiên Windows của Tray, không kết thúc dịch vụ
  SYSTEM, chính Tray hoặc các tiến trình giao diện Windows được bảo vệ.
- DNS proxy UDP/TCP trên `127.0.0.1:53`, lọc tên miền và tên miền con;
  trả NXDOMAIN khi chặn và gửi giải thích tới Tray. Luật miễn chặn có ưu tiên cao
  nhất; `111.vn` luôn được phép. Phụ huynh phải thêm miền trường/cứu hộ phù hợp.
- Lưu SQLite tại agent cả lịch sử và outbox; gửi theo lô tối đa 100 mục;
  server chống trùng bằng `(device_id, UUID sự kiện)` với ràng buộc DB.
- Retention đầy đủ cho **dữ liệu sự kiện F3**: quá 90 ngày tự xóa, xóa theo yêu
  cầu cả server/agent, có trạng thái xác nhận của từng thiết bị và chống gửi lại
  dữ liệu cũ. Nút xóa không xóa tài khoản, PIN, luật kiểm soát hoặc token ghép đôi.

Đây chưa phải toàn bộ F2/F3 của đề: SafeSearch, phân loại 200 mục, chống DoH,
biểu đồ/top 10, báo cáo PDF/CSV và báo cáo toàn bộ hoạt động cho trẻ chưa nằm
trong đợt triển khai này. Chính sách DNS hệ điều hành được bật thủ công trên máy
lab; không tự đổi DNS của máy đang phát triển khi chạy kiểm thử.

## Thiết kế sự kiện

Payload vẫn chỉ có bảy trường F3:

```json
{
  "ts": 1791530000,
  "device_id": "device-uuid",
  "child_id": "child-uuid",
  "type": "blocked_domain",
  "subject": "example.org",
  "duration_sec": 0,
  "policy_id": "filter:child-uuid:1"
}
```

Bao ngoài là `{id, generation, event, explanation}`. `id` là UUID được tạo một
lần tại agent và giữ nguyên khi retry. `generation` phục vụ hàng rào xóa dữ liệu.
`explanation` chứa `reason` và `rule_author`, là ảnh chụp lời giải thích tại thời
điểm chặn để thay đổi luật sau này không làm thay đổi lịch sử. Đây là mở rộng có
mục đích theo yêu cầu popup/lý do; không đưa nội dung nhạy cảm vào payload F3.

Tên miền được rút về registrable domain bằng Public Suffix List đóng gói offline
(ví dụ `portal.school.edu.vn` thành `school.edu.vn`). Danh sách suffix đóng gói
cần được cập nhật có kiểm chứng khi triển khai thật; miền lab `.test`/`.example`
dùng hai nhãn cuối. URL, query string, tiêu đề cửa sổ, đường dẫn tệp thực thi,
PID và hash thực thi không xuất hiện trong sự kiện gửi về server. Hash chỉ được
dùng để đối chiếu chính sách; đường dẫn/PID chỉ dùng trong bộ nhớ agent.

Các sự kiện được tạo hiện tại: `app_start`, `app_stop`, `blocked_app`,
`blocked_domain`. API chấp nhận đủ chín type theo F3 để tích hợp module tiếp theo.
Truy vấn A/AAAA/retry bị chặn được gộp thành một sự kiện cho cùng trẻ, tên miền
và lý do trong cửa sổ 5 giây, tránh popup lặp do một lần mở trang.

## Đồng bộ, chống trùng và xóa

1. Agent lấy `/api/device/event-state` trước khi upload.
2. Nếu generation của trẻ tăng, xóa lịch sử và outbox của trẻ đó trong một
   transaction SQLite; lưu generation mới. Trẻ khác không bị ảnh hưởng.
3. Agent xác nhận việc xóa bằng `/api/device/event-state/ack` sau khi commit cục bộ.
4. Agent tải/xác minh luật lọc đã ký HMAC cho thiết bị, lưu cache dùng khi offline.
5. Gửi batch. Chỉ đánh dấu đã gửi sau phản hồi ACK của server. Mất phản hồi sau
   commit thì retry nguyên UUID; server trả ACK mà không thêm dòng trùng.

Server khóa transaction ghi giữa ingestion và deletion để tránh race. Xóa trên
server tăng generation và xóa dữ liệu trong cùng transaction. Batch thế hệ cũ
bị discard kể cả tới sau yêu cầu xóa. Reuse UUID với payload/lý do khác trả 409;
toàn bộ batch rollback. Timestamp quá hạn bị discard, quá tương lai 5 phút trả
422. Các API kiểm tra quyền sở hữu và device_id, DELETE/PUT phụ huynh kiểm tra CSRF.

Thiết bị offline không thể xóa tức thì: dashboard hiển thị tên các thiết bị
chưa ACK, không tuyên bố đã hoàn tất cả hai phía. Khi thiết bị kết nối lại, nó
xóa trước khi gửi. Dữ liệu ghi trong thế hệ cũ khi offline cũng bị xóa, kể cả
được tạo sau lúc phụ huynh bấm nút. Metadata generation/ACK giữ tới vòng đời hồ
sơ/thiết bị để ngăn tái nhập; không chứa lịch sử truy cập hoặc lý do chặn.
Thiết bị đã thu hồi token nhưng chưa xác nhận xóa vẫn được liệt kê đang chờ;
không báo hoàn tất giả. Thiết bị đó cần cleanup dữ liệu cục bộ hoặc một quy trình
ghép lại/xác nhận hợp lệ; tự hết 90 ngày khi agent còn chạy.

Server dọn khi khởi động và mỗi giờ; agent dọn trong vòng đồng bộ 5 giây kể cả
upload thất bại và trước khi đọc/gửi lịch sử. Query server không trả mục quá
hạn trong khoảng giữa hai lần dọn. SQLite bật secure_delete; đây là xóa logic,
không cam kết xóa forensic trên WAL, ổ đĩa, snapshot hoặc bản sao lưu ngoài hệ thống.

## Cấu hình và demo trên máy lab

1. Cập nhật thư viện từ `requirements-lock.txt`, khởi động lại server và service
   bằng quy trình README/Setup-OGKAgent hiện có để tải mã mới. Schema mới là các
   bảng cộng thêm, không thay thế bảng dữ liệu Tuần 2.
2. Dashboard: chọn trẻ, vào **Kiểm soát ứng dụng và trang web**, bật kiểm soát;
   chọn allowlist website, thêm `example.org`, thêm cổng trường trong miễn chặn.
3. Service mở DNS proxy cục bộ. Upstream mặc định `1.1.1.1`; có thể đặt
   `OGK_DNS_UPSTREAM` trước khi khởi động service. Không đặt upstream loopback.
4. Trong PowerShell quản trị của **máy lab**, ghi lại DNS hiện tại và đặt DNS
   của adapter thử nghiệm về `127.0.0.1` bằng công cụ Windows. Nếu dừng/gỡ
   service, khôi phục DNS cũ trước để máy không mất phân giải tên miền.
5. Đăng nhập trẻ trong Tray, truy vấn tên miền lab bị chặn:

```powershell
Resolve-DnsName blocked.example.test -Server 127.0.0.1 -DnsOnly
```

   NXDOMAIN, popup lý do và dòng Sự kiện phải xuất hiện. Dashboard hiển thị sau
   lần đồng bộ kế tiếp. DNS cache trình duyệt/Windows có thể cần xóa trong demo.
   DNS proxy không biết truy vấn đến từ tab trình duyệt nào và có thể ghi nhận
   truy vấn nền của hệ điều hành trong lúc hồ sơ trẻ đang hoạt động.

6. Lấy tên/hash ứng dụng lab (không thử kết thúc ứng dụng có dữ liệu chưa lưu):

```powershell
python -m agent.filtering C:\Lab\sample.exe
```

   Nhập `sample.exe | <SHA-256>` vào danh sách bị chặn. Đổi tên bản sao của
   executable rồi chạy: vẫn phải bị kết thúc và có popup/lịch sử chặn.
   Phiên bản ứng dụng mới có hash khác cần cập nhật luật; protected Windows
   processes được miễn để giữ giao diện hệ điều hành hoạt động. Đây không phải
   cơ chế chống bypass hoàn chỉnh hoặc trình kiểm soát nhiều phiên RDP.

7. Tắt server, tạo sự kiện, khởi động lại: mỗi sự kiện chỉ có một dòng server.
8. Xóa dữ liệu từ dashboard khi agent offline: trạng thái chờ; reconnect agent:
   lịch sử cũ ở cả hai phía biến mất và trạng thái chuyển hoàn tất.

Luật nhận diện dùng SHA-256 làm căn cứ khi tên bị đổi. Tên trong rule giúp phụ
huynh nhận biết ứng dụng; cùng tên nhưng hash khác không được mạo danh ứng dụng
được phép. Blocklist ưu tiên allowlist; safety domain ưu tiên tất cả luật chặn.
Không thu thập/thực thi F2 khi Tray vắng mặt hoặc chưa có hồ sơ đăng nhập; DNS
proxy khi đó chỉ chuyển tiếp. DNS qua DoH/DoT, VPN, cache hoặc IP trực tiếp có
thể vượt bộ lọc này; các hạng mục chống bypass được xử lý ở giai đoạn tiếp theo.

## API mới

| Method | Path | Chức năng |
|---|---|---|
| GET | `/api/device/event-state` | Generation của hồ sơ trong household |
| POST | `/api/device/event-state/ack` | Xác nhận đã xóa bộ đệm |
| POST | `/api/device/activity-events` | Batch 1–100 envelope, ACK/discard theo UUID |
| GET | `/api/device/filtering` | Luật lọc đã ký HMAC, gắn thiết bị |
| GET/PUT | `/api/children/{child_id}/filtering` | Xem/lưu luật với expected_version |
| GET | `/api/children/{child_id}/activity-events` | Các lần chặn, offset/limit |
| DELETE | `/api/children/{child_id}/activity-data` | Xóa toàn bộ sự kiện F3 |
| GET | `/api/children/{child_id}/activity-data/deletion` | Trạng thái xác nhận xóa |

`/api/parent/events` vẫn là SSE cập nhật dashboard, không phải API lịch sử chặn.
Schema OpenAPI thực tế tại `/openapi.json`; bản snapshot Tuần 3 là
`openapi-week3.json`. Bản `openapi-agent-v1.yaml` trước đây là hợp đồng đích khác
namespace, chưa phải API chạy thực tế.

## Kết quả kiểm chứng ngày 09/10/2026

- Bộ pytest: **179 passed**, gồm các chức năng Tuần 2 và 25 case mới cho sự kiện,
  outbox, quyền sở hữu, CSRF, retention/xóa, DNS UDP/TCP, popup, giới hạn IPC và
  phạm vi kết thúc tiến trình trong Windows session. Có một cảnh báo deprecation
  từ Starlette TestClient hiện có; không đổi package ngoài lock của dự án.
- Ruff check/format và kiểm tra cú pháp JavaScript.
- Test F1 cũ được sửa để kiểm tra khoảng retry 10 giây đang có trong mã, gồm xác
  nhận không retry ở giây 2; không đổi hành vi khóa Windows trong đợt này.
- Đã thử mở dashboard với dữ liệu giả bằng trình duyệt kiểm tra nhưng kết nối
  localhost bị timeout trong môi trường phiên. Chưa xác nhận trực quan dashboard
  hoặc popup/service trên máy Windows lab thật; thực hiện các bước demo ở trên.
