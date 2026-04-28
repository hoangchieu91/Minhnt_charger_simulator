# MASTER PROMPT: PHÁT TRIỂN ESP32 GATEWAY TRẠM SẠC (TRU_V1.0 — Rev 2.0)

**Tác vụ:** Hãy đóng vai một chuyên gia lập trình nhúng ESP32 sử dụng **ESP-IDF v5.x** (C11 native). Viết Firmware cho thiết bị ESP32-WROVER-B đóng vai trò **IoT Gateway & Modbus RTU Master**, làm cầu nối giữa các tủ sạc (STM32 Slave) và hệ thống Cloud Server (MQTT).

---

## 1. YÊU CẦU PHẦN CỨNG & KẾT NỐI MẠNG (Ethernet First)
- **Board:** BL_GW_ESP32_Ver2.2 — ESP32-WROVER-B (8MB Flash, 4MB PSRAM).
- **Modbus RS485:** UART1 phần cứng (TX=GPIO17, RX=GPIO16, DE=GPIO14). Baudrate: `9600-8-N-1`. Cổng 2 dự phòng (TX=GPIO15, RX=GPIO36, DE=GPIO13).
- **Mạng LAN (Ethernet):** IC PHY LAN8742A kết nối RMII (thạch anh 25MHz tại GPIO0). **Bắt buộc LAN là kết nối chính** để chống nhiễu EMI từ contactor/rơ-le công suất.
- **Bảo mật AP:** Wi-Fi AP (`CHARGER_GW_MAC`) **CHỈ bật thủ công** bằng nhấn giữ nút GPIO34 trong 5 giây. KHÔNG tự phát sóng khi mất LAN.
- **MQTT TLS:** Hỗ trợ TLS/SSL (Port 8883) với CA cert lưu NVS.
- **RTC:** DS1307 (I2C SCL=GPIO32, SDA=GPIO33) + NTP sync.
- **LED:** GPIO5 (qua transistor MMBT3904). **Nút nhấn:** GPIO34 (5s=AP, 10s=Factory Reset).

---

## 2. LOCAL WEB DASHBOARD (ESP-IDF httpd + WebSocket)
ESP32 chạy `esp_http_server` (Port 80) + WebSocket `/ws` cho realtime push. Giao diện SPA lưu trong phân vùng `www` (LittleFS). Có xác thực admin password.

1. **Overview (Giám sát):** Realtime qua WebSocket — V, A, W, PF, kWh, Nhiệt độ, FSM State, Connector, Alarm flags cho tất cả trạm.
2. **Network/MQTT Config:** IP tĩnh, Gateway, Subnet. MQTT Host/Port/User/Pass. Upload TLS cert. Admin password.
3. **Modbus Setting:** `total_posts`, Polling rate, Start ID, Dynamic load balancing params (`current_limit` max cho nguồn chung).
4. **Diagnostics:** Manual Override (Start/Stop/Unlock/Clear/Force Fan), Crash Log viewer (từ `wdt_log`), OTA trigger, System health (heap/uptime/reset).

---

## 3. LOGIC GIAO THỨC MODBUS RTU
Logic đọc ghi bám sát `docs/MODBUS_REGISTER_MAP.md` (Rev 2.0):

- **(QUAN TRỌNG) Master Heartbeat Task:** Chu kỳ 3s, FC06 ghi giá trị (RTC timestamp) vào HR `0x0109` cho tất cả Slave online. Slave báo ERROR và cắt relay nếu >10s không nhận.
- **Polling Data Task:** Chu kỳ 1s, FC04 đọc **45 Input Registers** từ `0x0000` đến `0x002C`. Auto detect FSM state change → `esp_event_post()`. Auto detect alarm → event publish.
- **Control API (FC05):** 7 chức năng — Start(0x0000), Stop(0x0001), Unlock(0x0002), Clear(0x0003), Standby(0x0004), ForceFan(0x0005), FWUpdate(0x0006).
- **Dynamic Load Balancing:** FC06 ghi HR `0x010A` (current_limit) cho từng Slave khi cần giảm dòng.
- **Time Sync:** FC16 ghi HR `0x010C-0x010D` (Unix timestamp) mỗi 60s cho Slave.
- **Session Energy Limit:** FC06 ghi HR `0x010B` trước khi start_charge.
- **Diagnostics:** Đếm CRC errors, timeouts, retries cho từng Slave.

---

## 4. LOGIC GIAO THỨC MQTT (V3.4)
Gắn kết Modbus RAM cache lên MQTT Broker theo `docs/MQTT_PAYLOAD_V3.3.md` (đã nâng lên V3.4):

- **Gateway Status (`gw_status`):** 60s/lần. Bao gồm `fw_version`, `free_heap`, `reset_reason`, `eth_connected`, posts stats.
- **Telemetry (`tlm`):** 30s (charging) / 60s (idle). Bao gồm `frequency`, `power_factor`, `session_id`, `connector_status`, `alarm_flags`.
- **Session Status (`status`):** Event 10 (START) / 11 (COMPLETE) kèm `session_id` + kWh chốt.
- **Event (`evt`):** Realtime alarm push. 10 event codes (xem bảng enum).
- **Command ACK (`cmd_ack`):** Phản hồi ok/error + error_msg cho mọi command từ Server.
- **OTA Progress (`ota_progress`):** downloading → verifying → flashing → rebooting → success/rollback/failed.
- Cờ `RETAIN = TRUE` cho event, status, gw_status.

---

## 5. OTA & SYSTEM MONITOR
- **Dual OTA A/B:** Partition `ota_0` + `ota_1` (2.5MB mỗi cái). Rollback tự động nếu crash trong 60s.
- **OTA Server:** `https://nxchieu.duckdns.org/ota/check` — kiểm tra version mỗi 6 giờ hoặc trigger qua MQTT.
- **Store-and-Forward:** Mất MQTT → queue JSON vào `storage` partition (LittleFS, max 500KB FIFO) → replay khi có mạng.
- **Crash Analytics:** `wdt_log` partition lưu reset reason + timestamp RTC + heap snapshot. `coredump` partition lưu binary dump cho GDB.

---

## 6. KIẾN TRÚC THỰC THI (Architecture)
- **Framework:** ESP-IDF v5.x (C11 native). **KHÔNG dùng Arduino Core.**
- **Design Patterns:** Event-Driven (`esp_event_loop`), Component-Based, HAL Abstraction (`board_hal.h`), Chunked HTTP Response.
- **JSON:** `cJSON` (built-in ESP-IDF), dùng `cJSON_PrintUnformatted()` + `free()`.
- **FreeRTOS:** Pin Modbus tasks → Core 1 (tránh network stack Core 0). Tối thiểu 6 tasks.
- **Partition Table:** Custom 8MB (xem `docs/ESP32_ARCHITECTURE_PLAN.md`).
- **PSRAM:** `CONFIG_SPIRAM_USE_MALLOC=y` — tự động dùng PSRAM cho buffer lớn.

**Tham khảo chi tiết:**
- Kiến trúc & Tasks: `docs/ESP32_ARCHITECTURE_PLAN.md`
- Danh sách tính năng: `docs/ESP32_FEATURE_LIST.md`
- API Functions: `docs/ESP32_FUNCTION_LIST.md`
- Modbus Register Map: `docs/MODBUS_REGISTER_MAP.md`
- MQTT Payload: `docs/MQTT_PAYLOAD_V3.3.md` (V3.4)
