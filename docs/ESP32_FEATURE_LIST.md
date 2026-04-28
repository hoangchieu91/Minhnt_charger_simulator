# Danh sách Tính năng Hệ thống (ESP32 Gateway Ver 2.2 — Rev 2.0)

Tài liệu này liệt kê chi tiết các tính năng cần lập trình dựa trên phân tích phần cứng, chuẩn giao thức và kinh nghiệm ESP-IDF IoT Gateway.

## 1. Mạng & Kết nối (Connectivity)
- **[NET-01] Mạng LAN RMII Ethernet Khởi Động Trước:** Mặc định chạy cấu hình DHCP hoặc IP Tĩnh thông qua IC LAN8742A (Pin TX_EN=21, TXD0=19, RXD0=25...). Có thạch anh 25MHz ở GPIO0.
- **[NET-02] Wi-Fi AP Kích Hoạt Thủ Công (Bảo Mật):** AP cấu hình `CHARGER_GW_MAC` **KHÔNG tự phát sóng** khi mất mạng để chống hack xâm nhập LAN. Chỉ kích hoạt bằng **nhấn giữ nút GPIO34 trong 5 giây**. AP tự tắt sau 10 phút không hoạt động.
- **[NET-03] MQTT Client An Toàn:** Kết nối MQTT duy trì Keep-Alive. Hỗ trợ TLS/SSL (Port 8883) với chứng chỉ CA lưu trong NVS. Payload theo JSON V3.4. Cờ `RETAIN=true` cho event/status. Tự Reconnect sau 5s.
- **[NET-04] WebSocket Realtime:** Endpoint `/ws` trên HTTP Server cho phép push dữ liệu Modbus cache xuống Dashboard realtime thay vì AJAX polling.

## 2. Truyền thông Công nghiệp (Modbus RTU)
- **[MOD-01] Master Heartbeat Watchdog:** Chu kỳ 3-4s bắn FC06 vào HR `0x0109` cho mọi ID Slave. Báo OFFLINE nếu timeout >10s.
- **[MOD-02] Data Polling Quét Vòng Lặp:** Chu kỳ 1s dùng FC04 hỏi thanh ghi `0x0000` -> `0x002C` (45 registers). Dữ liệu update vào RAM. Bỏ qua tự động Slave mất kết nối để tối ưu độ trễ bus.
- **[MOD-03] Slave Control Wrappers:** FC05 nhanh cho 7 chức năng: Start, Stop, Unlock, Clear, Standby, Force Fan, Enter FW Update.
- **[MOD-04] Dynamic Load Balancing:** Gateway tính toán và ghi FC06 vào HR `0x010A` (current_limit) cho từng Slave để tránh quá tải nguồn chung khi nhiều trạm sạc đồng thời.
- **[MOD-05] Time Sync Master→Slave:** Ghi FC16 vào HR `0x010C-0x010D` (Unix timestamp) mỗi 60s để Slave có thời gian chuẩn cho Flash event log.
- **[MOD-06] Modbus Diagnostics:** Đếm CRC error, timeout, retries cho từng Slave. Expose qua Web và MQTT `gw_status`.

## 3. Bản tin IoT (MQTT Specification V3.4)
- **[IOT-01] Bản tin Gateway Status (`gw_status`):** Chu kỳ 60s. Bao gồm `fw_version`, `free_heap`, `min_free_heap`, `reset_reason`, `eth_connected`, thống kê posts.
- **[IOT-02] Bản tin Telemetry (`tlm`):** 30s khi sạc, 60s khi rảnh. Bao gồm BCD serial đồng hồ, `frequency`, `power_factor`, `session_id`, `connector_status`, `alarm_flags`.
- **[IOT-03] Bản tin Chốt Công Tơ (`status`):** Event 10 (STARTED) / Event 11 (COMPLETED) kèm `session_id` liên kết phiên.
- **[IOT-04] Bản tin Báo Lỗi (`evt`):** Push alert realtime. Bổ sung event code 7 (GROUND_FAULT) và 8 (OVERCURRENT).
- **[IOT-05] Command ACK (`cmd_ack`):** Phản hồi kết quả thực thi lệnh (ok/error + error_msg) cho Server.
- **[IOT-06] OTA Progress (`ota_progress`):** Báo cáo tiến trình tải/flash/rollback firmware từ xa.

## 4. OTA — Cập nhật Firmware Từ Xa
- **[OTA-01] Check Version Định Kỳ:** Kiểm tra firmware mới qua HTTPS endpoint `nxchieu.duckdns.org/ota/check` mỗi 6 giờ.
- **[OTA-02] Dual Partition A/B:** Flash firmware mới vào partition backup (`ota_1`), không ghi đè partition đang chạy.
- **[OTA-03] Auto Rollback:** Nếu firmware mới crash trong 60s sau boot, tự động rollback về bản cũ (`esp_ota_mark_app_invalid_rollback_and_reboot`).
- **[OTA-04] Trigger qua MQTT:** Server gửi command `ota_update` kèm URL firmware để kích hoạt OTA từ xa.

## 5. Store-and-Forward (Lưu trữ Offline)
- **[STF-01] Offline Queue:** Khi mất MQTT, tất cả event/telemetry/status được ghi vào phân vùng `storage` dạng JSON File xếp hàng.
- **[STF-02] Auto Replay:** Khi khôi phục mạng, replay toàn bộ queue theo thứ tự timestamp gốc.
- **[STF-03] FIFO Overflow:** Giới hạn 500KB queue. Xóa bản tin cũ nhất khi đầy.

## 6. Bảng điều khiển Quản trị Cục bộ (Local Web Dashboard)
- **[WEB-01] HTTP Server + WebSocket:** `esp_http_server` (Port 80) + WebSocket `/ws` cho realtime. Giao diện HTML/CSS/JS lưu trong phân vùng `www` (LittleFS).
- **[WEB-02] Tab Giám sát (Overview):** Push realtime qua WebSocket — V, A, W, kWh, Nhiệt độ, FSM State, Connector, Alarm flags.
- **[WEB-03] Cấu hình Network & MQTT:** Form IP, MQTT (Host/User/Pass), Upload TLS cert. Lưu NVS.
- **[WEB-04] Cấu hình Modbus:** `total_posts`, Polling rate, Start ID, Dynamic load balancing params.
- **[WEB-05] Diagnostics:** Manual Override (Unlock/Clear/Start/Stop), Crash Log viewer (từ `wdt_log`), OTA trigger, System health (heap/uptime/reset count).
- **[WEB-06] Xác thực Dashboard:** Mật khẩu admin lưu NVS. Session cookie/token cho mỗi phiên truy cập.

## 7. System Monitor & Crash Analytics
- **[SYS-01] Task Watchdog:** Đăng ký TWDT cho mọi FreeRTOS task. Ghi crash log vào phân vùng `wdt_log` kèm timestamp RTC.
- **[SYS-02] Reset Reason Tracking:** Đọc `esp_reset_reason()` sau mỗi lần boot, ghi nhận vào `wdt_log` và `gw_status`.
- **[SYS-03] Core Dump to Flash:** Khi CPU crash/panic, binary dump tự động ghi vào phân vùng `core_dump`. Có thể download qua Web Dashboard hoặc OTA Server để phân tích GDB.
- **[SYS-04] Heap Monitor:** Kiểm tra `free_heap` định kỳ, cảnh báo nếu < 20KB.

## 8. Ngoại vi & Cảnh báo Phần cứng
- **[HW-01] DS1307 RTC Đồng Bộ:** I2C (SCL=32, SDA=33). Timestamp chuẩn cho payload JSON. Đồng bộ NTP định kỳ. Fallback uptime nếu I2C lỗi.
- **[HW-02] Đèn LED Báo Hiệu:** GPIO 5. Pattern: 1Hz=Bình thường, Sáng liên tục=Đang lấy IP, Chớp nhanh=Lỗi Modbus/MQTT, 2 chớp ngắn=OTA đang chạy.
- **[HW-03] Nút Nhấn Đa Năng (GPIO 34):**
  - Nhấn giữ 5s → Kích hoạt Wi-Fi AP cấu hình.
  - Nhấn giữ 10s → Factory Reset (Clear NVS).
  - Nhấn ngắn 2 lần → Hiển thị IP trên LED (nếu có OLED).
