# Danh sách Hàm Lập trình Cốt lõi (ESP32 Gateway Ver 2.2 — Rev 2.0)

Bộ khung nguyên mẫu API theo kiến trúc **ESP-IDF v5.x native C11**, sử dụng `esp_event_loop` cho inter-module communication và FreeRTOS tasks.

> [!NOTE]
> - Tất cả types/events/structs được định nghĩa tập trung trong `project_common.h`.
> - GPIO mapping nằm trong `board_hal.h` với macro `#if defined(CONFIG_IDF_TARGET_xxx)`.
> - JSON sử dụng `cJSON` (built-in ESP-IDF), KHÔNG dùng ArduinoJson.

---

## 0. Core Definitions (`project_common.h`)
```c
// Event bases
ESP_EVENT_DECLARE_BASE(MODBUS_EVENT);   // EVT_DATA_UPDATED, EVT_STATE_CHANGED, EVT_SLAVE_OFFLINE
ESP_EVENT_DECLARE_BASE(MQTT_EVENT);     // EVT_CMD_RECEIVED, EVT_CONNECTED, EVT_DISCONNECTED
ESP_EVENT_DECLARE_BASE(SYSTEM_EVENT);   // EVT_OTA_STARTED, EVT_FACTORY_RESET, EVT_LOW_HEAP

// Charger state struct (RAM cache, 1 per slave)
typedef struct {
    uint16_t    registers[45];      // Raw FC04 data (0x0000-0x002C)
    uint8_t     slave_id;
    bool        online;
    uint32_t    last_seen_ms;
    uint8_t     prev_fsm_state;     // Detect state transitions
    uint16_t    crc_errors;         // Modbus CRC error count
    uint16_t    timeout_count;      // Modbus timeout count
} charger_state_t;

extern charger_state_t charger_states[CONFIG_MAX_POSTS];
```

## 0b. Hardware Abstraction (`board_hal.h`)
```c
// RS485 Port 1 (Modbus Master)
#define PIN_RS485_1_TX          GPIO_NUM_17
#define PIN_RS485_1_RX          GPIO_NUM_16
#define PIN_RS485_1_DE          GPIO_NUM_14
#define UART_RS485_1            UART_NUM_1

// RS485 Port 2 (Reserved)
#define PIN_RS485_2_TX          GPIO_NUM_15
#define PIN_RS485_2_RX          GPIO_NUM_36
#define PIN_RS485_2_DE          GPIO_NUM_13
#define UART_RS485_2            UART_NUM_2

// Ethernet RMII (LAN8742A)
#define PIN_ETH_TX_EN           GPIO_NUM_21
#define PIN_ETH_TXD0            GPIO_NUM_19
#define PIN_ETH_TXD1            GPIO_NUM_22
#define PIN_ETH_MDC             GPIO_NUM_23
#define PIN_ETH_MDIO            GPIO_NUM_18
#define PIN_ETH_REF_CLK         GPIO_NUM_0
#define PIN_ETH_CRS_DV          GPIO_NUM_27
#define PIN_ETH_RXD0            GPIO_NUM_25
#define PIN_ETH_RXD1            GPIO_NUM_26

// I2C (DS1307 RTC)
#define PIN_I2C_SCL             GPIO_NUM_32
#define PIN_I2C_SDA             GPIO_NUM_33

// Peripherals
#define PIN_STATUS_LED          GPIO_NUM_5
#define PIN_BUTTON              GPIO_NUM_34
```

---

## 1. Network Manager (`network_manager.h`)
- `esp_err_t network_manager_init(void)` — Khởi tạo Ethernet RMII (LAN8742A). Đọc NVS xác định Static IP vs DHCP. Đăng ký event handler cho `IP_EVENT` / `ETH_EVENT`.
- `esp_err_t wifi_ap_start(void)` — Kích hoạt SoftAP `CHARGER_GW_{MAC}`. Chỉ gọi khi nhấn giữ nút GPIO34 >= 5s.
- `esp_err_t wifi_ap_stop(void)` — Tắt AP sau 10 phút timeout.
- `bool network_is_connected(void)` — Return `true` nếu Ethernet link up + có IP hợp lệ.
- `void network_get_ip_info(char *ip_str, size_t len)` — Lấy IP address hiện tại dạng string.

## 2. Modbus RTU Master (`modbus_master.h`)

> [!IMPORTANT]
> FC04 = Read **Input** Registers, FC03 = Read **Holding** Registers. Không nhầm lẫn.

- `esp_err_t modbus_master_init(void)` — Khởi tạo `uart_driver_install()` trên UART1 (GPIO 16/17), `gpio_set_direction()` cho DE pin (GPIO 14). Baudrate 9600-8N1.
- `void task_modbus_polling(void *pvParameters)` — FreeRTOS task. Loop ID 1→`total_posts`:
  1. `modbus_read_input_registers()` — FC04 đọc 45 regs (0x0000-0x002C).
  2. Detect FSM state change → `esp_event_post(MODBUS_EVENT, EVT_STATE_CHANGED, ...)`.
  3. Detect alarm → `esp_event_post(MODBUS_EVENT, EVT_ALARM_TRIGGERED, ...)`.
  4. Mark offline nếu timeout 3 lần liên tiếp.
- `esp_err_t modbus_read_input_registers(uint8_t slave_id, uint16_t start_addr, uint16_t num_regs, uint16_t *rx_buffer)` — Gửi FC04, parse response, kiểm tra CRC. Return `ESP_OK` hoặc `ESP_ERR_TIMEOUT`.
- `esp_err_t modbus_write_single_register(uint8_t slave_id, uint16_t addr, uint16_t value)` — FC06. Dùng cho heartbeat (0x0109), current_limit (0x010A), time_sync.
- `esp_err_t modbus_write_multiple_registers(uint8_t slave_id, uint16_t start_addr, uint16_t num_regs, const uint16_t *values)` — FC16. Dùng cho time_sync (0x010C-0x010D).
- `esp_err_t modbus_write_coil(uint8_t slave_id, uint16_t addr, bool on)` — FC05. `on=true` → ghi 0xFF00.
- `void task_modbus_heartbeat(void *pvParameters)` — Task riêng, chu kỳ 3s. Ghi FC06 vào HR 0x0109 cho tất cả Slave online.
- `void modbus_execute_command(uint8_t slave_id, modbus_cmd_t cmd)` — Wrapper: nhận command enum (START/STOP/UNLOCK/CLEAR/STANDBY/FORCE_FAN/FW_UPDATE) → gọi FC05 tương ứng.

## 3. MQTT Service (`cloud_service.h`)
- `esp_err_t mqtt_service_init(void)` — Đọc NVS (host, port, user, pass, ca_cert). Khởi tạo `esp_mqtt_client_init()` với TLS nếu có cert.
- `void mqtt_event_handler(void *args, esp_event_base_t base, int32_t event_id, void *event_data)` — Handle CONNECT, DISCONNECT, DATA, ERROR events.
- `esp_err_t mqtt_publish_gw_status(void)` — JSON: `fw_version`, `free_heap`, `reset_reason`, `eth_connected`, stats. Topic `charging/st/{mac}/gw_status`. Chu kỳ 60s.
- `esp_err_t mqtt_publish_telemetry(uint8_t slave_id)` — Map `charger_states[id].registers[]` → JSON TLM V3.4. Topic `charging/st/{mac}/post/{id}/tlm`.
- `esp_err_t mqtt_publish_event(uint8_t slave_id, uint8_t msg_type, uint8_t event_code, float value)` — JSON evt. QOS1, Retain=true. Topic `.../evt`.
- `esp_err_t mqtt_publish_session_status(uint8_t slave_id, bool is_start, uint16_t session_id)` — Chốt kWh start/end. Topic `.../status`.
- `esp_err_t mqtt_publish_cmd_ack(uint8_t slave_id, const char *cmd, const char *result, const char *error_msg)` — Phản hồi thực thi lệnh. Topic `.../cmd_ack`.
- `esp_err_t mqtt_publish_ota_progress(const char *status, uint8_t progress, const char *error)` — OTA tiến trình. Topic `.../ota_progress`.
- `void mqtt_on_state_changed(void *args, esp_event_base_t base, int32_t id, void *data)` — Event handler lắng nghe `MODBUS_EVENT/EVT_STATE_CHANGED` → tự publish event/status.

## 4. Store-and-Forward (`offline_queue.h`)
- `esp_err_t offline_queue_init(void)` — Mount phân vùng `storage` (LittleFS). Scan file queue hiện có.
- `esp_err_t offline_queue_push(const char *topic, const char *payload, int qos, bool retain)` — Ghi bản tin vào file JSON. Tăng counter.
- `esp_err_t offline_queue_replay(void)` — Đọc lần lượt file từ cũ→mới, publish lên MQTT, xóa file sau khi publish thành công.
- `size_t offline_queue_get_size(void)` — Dung lượng queue hiện tại (bytes).
- `void offline_queue_trim(size_t max_bytes)` — FIFO: xóa bản tin cũ nhất cho đến khi < max_bytes.

## 5. OTA Service (`ota_service.h`)
- `esp_err_t ota_service_init(void)` — Đăng ký handler cho MQTT command `ota_update`.
- `esp_err_t ota_check_version(const char *url)` — HTTPS GET endpoint, so sánh `PROJECT_VER` vs server version.
- `esp_err_t ota_perform_update(const char *firmware_url)` — Download firmware → `esp_ota_begin()` → write chunks → `esp_ota_end()` → `esp_ota_set_boot_partition()`. Publish progress qua MQTT.
- `void ota_health_check(void)` — Gọi sau boot 60s: nếu firmware mới chạy ổn → `esp_ota_mark_app_valid_cancel_rollback()`. Nếu crash trước 60s → tự rollback.

## 6. Local Web Server (`web_ui.h`)
- `esp_err_t webserver_init(void)` — `httpd_start()` trên port 80. Mount phân vùng `www` (LittleFS). Đăng ký URI handlers.
- `esp_err_t ws_handler(httpd_req_t *req)` — WebSocket handler tại `/ws`. Push JSON data mỗi 1s từ charger_states[].
- `esp_err_t api_get_overview(httpd_req_t *req)` — `GET /api/overview`. Dùng `httpd_resp_sendstr_chunk()` để stream JSON lớn.
- `esp_err_t api_post_config(httpd_req_t *req)` — `POST /api/config`. Parse JSON body → Write NVS → respond OK → schedule reboot.
- `esp_err_t api_post_control(httpd_req_t *req)` — `POST /api/control`. Parse `{slave_id, cmd}` → `modbus_execute_command()` → respond ACK.
- `esp_err_t api_get_crash_log(httpd_req_t *req)` — `GET /api/crash_log`. Đọc phân vùng `wdt_log`, stream TSV.
- `esp_err_t api_post_ota(httpd_req_t *req)` — `POST /api/ota`. Trigger OTA update từ Web Dashboard.

## 7. System Monitor (`system_monitor.h`)
- `esp_err_t system_monitor_init(void)` — Đăng ký TWDT cho tasks. Đọc `esp_reset_reason()`. Ghi boot event vào `wdt_log`.
- `void system_log_crash(esp_reset_reason_t reason, uint32_t rtc_timestamp)` — Append dòng TSV vào phân vùng `wdt_log`: `timestamp | reason_code | free_heap | uptime`.
- `system_health_t system_get_health(void)` — Return struct: `free_heap`, `min_free_heap`, `uptime_s`, `task_count`, `reset_count`, `reset_reason`.
- `void task_system_monitor(void *pvParameters)` — Task chu kỳ 10s: check heap, post `SYSTEM_EVENT/EVT_LOW_HEAP` nếu < 20KB.

## 8. Time Manager (`time_manager.h`)
- `esp_err_t time_manager_init(void)` — Khởi tạo I2C driver, sync DS1307 RTC (SCL=32, SDA=33).
- `uint32_t time_get_unix(void)` — Ưu tiên: NTP → RTC DS1307 → `esp_log_early_timestamp()` fallback.
- `esp_err_t time_sync_ntp(void)` — SNTP sync từ `pool.ntp.org`. Cập nhật RTC DS1307 sau khi sync.
- `esp_err_t time_sync_to_slaves(void)` — Ghi Unix timestamp vào HR 0x010C-0x010D cho tất cả Slave online.

## 9. Hardware Peripherals (`hardware_manager.h`)
- `esp_err_t hardware_init(void)` — GPIO config: LED (GPIO5 output), Button (GPIO34 input pullup). ISR cho button.
- `void led_update(system_state_t state)` — Pattern: 1Hz=Normal, Solid=Getting IP, Fast=Error, Double=OTA.
- `void button_isr_handler(void *arg)` — Đặt flag, debounce 50ms. Task xử lý: 5s→AP, 10s→Factory Reset.
- `esp_err_t factory_reset(void)` — `nvs_flash_erase()` → `esp_restart()`.
- `void meter_serial_bcd_to_string(const uint16_t regs[3], char *out, size_t len)` — Convert BCD registers 0x0023-0x0025 thành chuỗi ASCII 12 ký tự.
