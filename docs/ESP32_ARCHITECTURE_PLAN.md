# Kế hoạch Triển khai & Kiến trúc Hệ thống (ESP32 Gateway Ver 2.2 — Rev 2.0)

Tài liệu này định nghĩa kiến trúc phần mềm và kế hoạch triển khai cho ESP32 Gateway đóng vai trò Modbus RTU Master và MQTT Bridge, dựa trên nền tảng **ESP-IDF v5.x** (C11 native).

## 1. Tổng quan Kiến trúc Phần cứng
- **Vi điều khiển:** ESP32-WROVER-B (8MB Flash, 4MB PSRAM)
- **Kết nối Mạng:** LAN8742A (Ethernet RMII) — kết nối chính. Wi-Fi AP chỉ dùng cho cấu hình thủ công.
- **Modbus Trạm sạc:** RS485 Cổng 1 (ISO3082/MAX3485, UART1, DE=GPIO14). RS485 Cổng 2 dự phòng (UART2, DE=GPIO13).
- **Ngoại vi:** DS1307 RTC (I2C SCL=32, SDA=33), Nút nhấn (GPIO 34), Status LED (GPIO 5).

## 2. Kiến trúc Phần mềm (ESP-IDF + FreeRTOS)

### 2.1. Cấu trúc Source Code (Component-Based)
```
project/
├── main/
│   └── app_main.c                  # Entry point, khởi tạo tất cả modules
├── components/
│   ├── common/                      # project_common.h, board_hal.h
│   ├── network_manager/             # Ethernet RMII + WiFi AP fallback
│   ├── modbus_master/               # RS485 driver + polling + heartbeat
│   ├── cloud_service/               # MQTT client + TLS + offline queue
│   ├── offline_queue/               # Store-and-Forward (LittleFS)
│   ├── web_ui/                      # HTTP server + WebSocket + REST API
│   ├── ota_service/                 # HTTPS OTA + rollback protection
│   ├── system_monitor/              # WDT, crash log, heap tracking
│   ├── time_manager/                # NTP + DS1307 RTC + slave sync
│   └── hardware_manager/            # LED, Button, Factory Reset
├── web_app/                         # React/Vanilla JS SPA (Vite build → LittleFS)
├── partitions.csv
├── sdkconfig.defaults
└── CMakeLists.txt
```

### 2.2. Inter-module Communication (Event-Driven)
Các module giao tiếp qua `esp_event_loop` thay vì flags/polling trực tiếp:

```
┌─────────────┐   EVT_STATE_CHANGED    ┌──────────────┐
│ modbus_master├──────────────────────►│ cloud_service │ → MQTT publish
│  (polling)   ├──────────────────────►│ (subscriber)  │
└──────┬───────┘   EVT_ALARM_TRIGGERED └──────┬────────┘
       │                                       │
       │  EVT_DATA_UPDATED                     │ EVT_CMD_RECEIVED
       ▼                                       ▼
┌─────────────┐                        ┌──────────────┐
│   web_ui    │◄──── WebSocket push ───│ modbus_master │ ← execute command
│ (dashboard) │                        │ (control API) │
└─────────────┘                        └──────────────┘
```

### 2.3. FreeRTOS Tasks

| Task                    | Stack | Priority     | Core   | Chu kỳ       | Mô tả                                         |
| ----------------------- | ----- | ------------ | ------ | ------------ | --------------------------------------------- |
| `task_modbus_polling`   | 4096  | 5 (Cao nhất) | Core 1 | 1s           | Đọc FC04 (45 regs), detect state change/alarm |
| `task_modbus_heartbeat` | 2048  | 4            | Core 1 | 3s           | Ghi FC06 vào HR 0x0109                        |
| `task_mqtt_publish`     | 8192  | 3            | Core 0 | Event-driven | Publish TLM/EVT/Status khi nhận event         |
| `task_mqtt_subscribe`   | 4096  | 3            | Core 0 | Blocking     | Lắng nghe command từ Server                   |
| `task_webserver`        | 8192  | 2            | Core 0 | Async        | HTTP + WebSocket requests                     |
| `task_system_monitor`   | 2048  | 1 (Thấp)     | Core 0 | 10s          | Heap check, WDT feed                          |
| `task_time_sync`        | 2048  | 1            | Core 0 | 60s          | NTP sync + push time to Slaves                |

> **Pin-to-Core:** Modbus tasks chạy trên Core 1 (không bị ảnh hưởng bởi WiFi/networking stack trên Core 0).

### 2.4. Network Task Logic

```
Boot → Init Ethernet RMII (LAN8742A)
  ├─ Ethernet Link Up → DHCP hoặc Static IP → MQTT Connect → Normal Operation
  ├─ Ethernet Link Down → Modbus vẫn chạy bình thường
  │                       Store-and-Forward queue events vào Flash
  │                       LED: Chớp nhanh
  └─ Button GPIO34 giữ 5s → Bật Wi-Fi AP (CHARGER_GW_MAC)
                             AP tự tắt sau 10 phút
                             Chỉ phục vụ Web Config, KHÔNG kết nối MQTT
```

## 3. Cấu trúc Bộ nhớ & Phân vùng (Flash 8MB Custom Partition)

### 3.1. Partition Table (`partitions.csv`)

> [!NOTE]
> Tất cả phân vùng data đều có kích thước là **bội số 64KB** (0x10000) để tránh phân mảnh Flash.
> Chi tiết cơ chế Store-and-Forward xem tại `docs/ESP32_STORE_AND_FORWARD.md`.

```csv
# Name,    Type, SubType,  Offset,    Size,       # KB    ×64K  Note
nvs,       data, nvs,      0x9000,    0x6000,     # 24KB  -     System (IDF standard)
otadata,   data, ota,      0xF000,    0x2000,     # 8KB   -     System (IDF fixed)
phy_init,  data, phy,      0x11000,   0x1000,     # 4KB   -     System (IDF fixed)
ota_0,     app,  ota_0,    0x20000,   0x280000,   # 2560K 40    Firmware chính
ota_1,     app,  ota_1,    0x2A0000,  0x280000,   # 2560K 40    Firmware OTA backup
www,       data, spiffs,   0x520000,  0xC0000,    # 768K  12    Web Dashboard assets
storage,   data, spiffs,   0x5E0000,  0x1C0000,   # 1792K 28    Offline queue + data
wdt_log,   data, spiffs,   0x7A0000,  0x20000,    # 128K  2     Crash/WDT log
coredump,  data, coredump, 0x7C0000,  0x40000,    # 256K  4     Core dump cho GDB
# Total: 0x7C0000 + 0x40000 = 0x800000 = 8MB ✓ (Flash sử dụng 100%)
```

| Phân vùng | Kích thước | ×64KB | Filesystem | Mô tả |
|-----------|-----------|-------|------------|-------|
| `nvs` | 24KB | — | NVS API | IP, MQTT Cert/Auth, total_posts, admin password |
| `otadata` | 8KB | — | OTA API | Con trỏ boot A/B partition |
| `phy_init` | 4KB | — | PHY API | RF calibration |
| `ota_0` | 2560KB | 40 | App | Firmware chính (factory) |
| `ota_1` | 2560KB | 40 | App | Firmware OTA backup |
| `www` | 768KB | 12 | LittleFS | HTML/CSS/JS Dashboard (Vite build, gzip ~300KB) |
| `storage` | 1792KB | 28 | LittleFS | **Offline queue binary blocks + session cache + config backup** (xem `ESP32_STORE_AND_FORWARD.md`) |
| `wdt_log` | 128KB | 2 | LittleFS | Crash log TSV: `timestamp\|reason\|heap\|uptime` |
| `coredump` | 256KB | 4 | Core Dump | Binary crash snapshot cho GDB |

> **Storage capacity:** 1792KB / 64 bytes = **28,672 records**. Với 10 trạm × TLM mỗi 30s = đủ lưu **~24 giờ offline**.

> **Tổng:** 24K + 8K + 4K + 2560K + 2560K + 768K + 1792K + 128K + 256K = **8100KB + system ≈ 8MB** (Flash sử dụng 100%)

### 3.2. RAM / Heap
- Khởi tạo `charger_states[CONFIG_MAX_POSTS]` trên heap (khoảng 45×2 + 12 bytes × MAX_POSTS).
- PSRAM (4MB trên WROVER-B): Dùng cho JSON string buffer lớn, WebSocket frame buffer, OTA download buffer.
- `sdkconfig`: `CONFIG_SPIRAM_USE_MALLOC=y` để tự động sử dụng PSRAM khi heap nội bộ cạn.

### 3.3. sdkconfig.defaults
```ini
CONFIG_PARTITION_TABLE_CUSTOM=y
CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions.csv"
CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y
CONFIG_ESP_MAIN_TASK_STACK_SIZE=8192
CONFIG_HTTPD_WS_SUPPORT=y
CONFIG_HTTPD_MAX_REQ_HDR_LEN=1024
CONFIG_HTTPD_MAX_URI_LEN=1024
CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y
CONFIG_ESP_TASK_WDT_PANIC=y
CONFIG_ESP_COREDUMP_ENABLE_TO_FLASH=y
CONFIG_MBEDTLS_CERTIFICATE_BUNDLE=y
CONFIG_SPIRAM_USE_MALLOC=y
```

## 4. Trình tự Triển khai (Execution Plan)

### Giai đoạn 1: Foundation (Hardware + Network)
- Tạo project ESP-IDF, thiết lập `partitions.csv`, `sdkconfig.defaults`.
- Code `project_common.h` (structs, events) + `board_hal.h` (GPIO mapping).
- Code `network_manager`: Ethernet RMII LAN8742A, DHCP/Static IP, WiFi AP manual.
- Code `time_manager`: DS1307 I2C + NTP sync.
- Code `hardware_manager`: LED patterns, button ISR, factory reset.
- **Verify:** Ping qua Ethernet, RTC hiển thị thời gian đúng.

### Giai đoạn 2: Modbus Master
- Code `modbus_master`: UART driver, FC04/FC05/FC06/FC16 wrappers, CRC16.
- Code polling task + heartbeat task.
- Code event posting: `EVT_STATE_CHANGED`, `EVT_ALARM_TRIGGERED`.
- **Verify:** Đọc được data từ STM32 Slave qua RS485, heartbeat hoạt động.

### Giai đoạn 3: MQTT + Store-and-Forward
- Code `cloud_service`: esp_mqtt client, TLS support, event handlers.
- Code `offline_queue`: LittleFS queue, push/replay/trim.
- Tích hợp event-driven: Modbus event → auto publish MQTT.
- Code `cmd_ack` response flow.
- **Verify:** Publish TLM/EVT lên broker, rút LAN → queue lưu → cắm lại → replay.

### Giai đoạn 4: Local Web UI
- Build React/Vanilla JS SPA với Vite.
- Upload build output vào phân vùng `www` (LittleFS).
- Code `web_ui`: HTTP server + WebSocket + REST API endpoints.
- **Verify:** Truy cập Dashboard qua IP LAN, WebSocket realtime data.

### Giai đoạn 5: OTA + System Monitor
- Code `ota_service`: HTTPS download, dual partition, rollback 60s health check.
- Code `system_monitor`: WDT, crash log, heap tracking.
- **Verify:** Trigger OTA qua MQTT, rollback test (flash firmware lỗi cố ý).

### Giai đoạn 6: Testing & Tối ưu
- Stress test: 10 Slaves × polling 1s × 24h liên tục.
- Memory leak detection: heap monitoring + coredump analysis.
- Modbus bus integrity: CRC error rate, timeout statistics.
- Store-and-Forward: rút LAN 1 giờ, kiểm tra replay đầy đủ.
