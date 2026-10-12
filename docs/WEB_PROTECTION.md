# DNS cho trình duyệt trên Windows

Service tự cấu hình DNS khi trẻ đã đăng nhập, Tray còn heartbeat và policy
kiểm soát ứng dụng/website được bật. Không cần chọn DNS trong terminal.
Agent kiểm tra lại mỗi 10 giây (cộng thời gian Windows xử lý cấu hình), nhận cả
adapter mới khi chuyển Wi-Fi/Ethernet. Chỉ cấu hình sau khi proxy UDP/TCP chạy
trên cả `127.0.0.1:53` và `[::1]:53`.

## Sử dụng

1. Cập nhật mã, cài agent bằng `scripts/Setup-OGKAgent.ps1` nếu chưa cài.
   Nếu đã cài, chạy `Restart-Service OpenGuardKidsAgentTest` trong PowerShell
   quản trị, thoát rồi mở lại Tray để nhận giao diện mới.
2. Đăng nhập hồ sơ trẻ trên Tray, bật kiểm soát website trên dashboard và lưu.
3. Trong tab giải thích dữ liệu của Tray, chờ **DNS trình duyệt: đã cấu hình**.
   Đóng hoàn toàn rồi mở lại Chrome/Edge/Firefox để nhận policy Secure DNS.
4. Thêm `example.com` vào danh sách chặn, lưu và đợi đồng bộ. Truy cập
   `https://example.com` bằng thanh địa chỉ: phải lỗi DNS, có sự kiện chặn trên
   Tray/dashboard. Kiểm tra một website được phép vẫn mở được.
5. Tắt kiểm soát hoặc đăng xuất trẻ: agent khôi phục DNS và policy trình duyệt.
   Dừng service/gỡ bằng cleanup cũng thực hiện khôi phục.

Đây là cấu hình cấp máy, ảnh hưởng mọi ứng dụng và người dùng Windows trong
thời gian bật. Bản hiện tại chưa phân biệt nhiều phiên Windows đồng thời.
Trình duyệt có thể hiển thị thông báo được quản lý do policy này.

## Cấu hình và phục hồi

- IPv4 dùng `127.0.0.1`, IPv6 dùng `::1`; upstream riêng vẫn là `1.1.1.1`
  (hoặc `OGK_DNS_UPSTREAM`). Không đặt DNS phụ công khai.
- Chrome/Edge: `DnsOverHttpsMode=off`; Firefox: `DNSOverHTTPS.Enabled=0`,
  `Locked=1`. Chỉ lưu/khôi phục các giá trị policy này, không xóa khóa policy khác.
- Lưu DNS tĩnh hoặc chế độ tự động theo từng GUID adapter và từng họ địa chỉ,
  cùng các giá trị browser policy cũ trong
  `%ProgramData%\OpenGuardKids\network-backup.json` (thư mục có ACL quản trị).
  Ghi bản sao trước khi thay đổi; khởi động lại không ghi đè bản gốc.
- Nếu cấu hình lỗi, thử khôi phục, báo lỗi trên Tray và giữ phần chưa phục hồi
  để thử lại. Cleanup từ chối xóa dữ liệu/runtime khi còn lỗi khôi phục.
- Nếu service bị kill hoặc máy tắt đột ngột, DNS có thể còn trỏ loopback trong
  khi proxy không chạy. Khởi động service lại hoặc chạy lệnh dưới bằng quyền
  quản trị **sau khi dừng service**:

  ```powershell
  .\.venv-service\Scripts\python.exe -m agent.web_protection --restore
  ```

Nếu adapter đã bị gỡ, giữ file backup, kết nối lại adapter và thử lại.
Không sửa DNS thủ công trong lúc bảo vệ đang bật; agent quản lý cấu hình đó.

## Giới hạn và kiểm thử

Trạng thái “đã cấu hình” xác nhận agent đã ghi cấu hình, không chứng minh mọi
trình duyệt đang dùng nó. Kiểm tra `edge://policy`, `chrome://policy` hoặc
`about:policies` sau khi mở lại trình duyệt. GPO của tổ chức, VPN, DoH riêng
trong phần mềm khác, DNS mã hóa cấp hệ điều hành, IP trực tiếp và cache/kết nối
đã mở có thể vượt bộ lọc. Chưa triển khai WFP hoặc firewall chống bypass.

Sự kiện vẫn là truy vấn tên miền, không phải số lượt mở trang/thời gian ở trang.
Không thu URL đầy đủ hay nội dung HTTPS. Khi tắt kiểm soát, DNS hệ thống được
khôi phục nên không tiếp tục thu truy vấn trình duyệt qua proxy.

Test `tests/test_web_protection.py` dùng backend giả để kiểm tra rollback,
DNS tĩnh/tự động, restart, adapter mới và phục hồi thất bại. Test không sửa
DNS/registry máy thật. Cần nghiệm thu trình duyệt thật theo các bước trên.

Policy tham khảo: [Edge](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-browser-policies/dnsoverhttpsmode),
[Chrome](https://chromeenterprise.google/policies/#DnsOverHttpsMode),
[Firefox](https://mozilla.github.io/policy-templates/#dnsoverhttps).
