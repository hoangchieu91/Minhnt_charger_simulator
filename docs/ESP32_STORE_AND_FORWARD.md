# Store-and-Forward & Error Resilience Specification (ESP32 Gateway Ver 2.2)

Tài liệu chi tiết thiết kế hệ thống lưu trữ bản tin offline, cờ đồng bộ MQTT, và các cơ chế phòng chống lỗi/crash.

---

## 1. Tổng quan Storage Partition

Phân vùng `storage` (LittleFS, 1.75MB) lưu trữ các bản tin MQTT chưa publish thành công dưới dạng **binary compact blocks 64 bytes**. Khi MQTT reconnect, hệ thống tự replay theo thứ tự timestamp.

**Tại sao dùng Binary Block 64 bytes thay vì JSON file?**
- Tiết kiệm Flash write cycle (JSON 200-500 bytes → binary chỉ 64 bytes).
- Cấu trúc cố định → không bị phân mảnh file system.
- Dễ scan, seek, đếm record. Không cần parse text.
- JSON được reconstruct tại thời điểm publish (chỉ tốn RAM tạm thời).

**Dung lượng:** 1,792KB / 64 bytes = **28,672 records** tối đa.  
Với 10 trạm × TLM mỗi 30s = 20 records/phút → đủ lưu **~24 giờ offline** liên tục.

---

## 2. Cấu trúc Binary Block (64 Bytes)

### 2.1. Block Header (16 bytes)

| Offset | Size | Field | Mô tả |
|--------|------|-------|-------|
| `0x00` | 2 | `magic` | `0xBEEF` = record hợp lệ. Giá trị khác = bỏ qua. |
| `0x02` | 1 | `sync_flag` | **Cờ đồng bộ MQTT** (xem bảng bên dưới) |
| `0x03` | 1 | `msg_type` | Loại bản tin (xem enum) |
| `0x04` | 1 | `slave_id` | Modbus Slave ID (0 = bản tin cấp Gateway) |
| `0x05` | 1 | `qos` | MQTT QoS (0 hoặc 1) |
| `0x06` | 1 | `retain` | MQTT Retain flag (0 hoặc 1) |
| `0x07` | 1 | `retry_count` | Số lần đã thử publish (max 5, sau đó discard) |
| `0x08` | 4 | `timestamp` | Unix timestamp (uint32_t, từ RTC hoặc uptime) |
| `0x0C` | 4 | `sequence` | Số thứ tự toàn cục (tăng đơn điệu, dùng để replay đúng thứ tự) |

### 2.2. Sync Flag — Cờ Trạng thái Đồng bộ MQTT

| Giá trị | Tên | Ý nghĩa | Hành vi |
|---------|-----|---------|---------|
| `0x00` | `SLOT_FREE` | Block trống, chưa ghi | Có thể ghi đè record mới |
| `0xAA` | `SLOT_PENDING` | Bản tin chưa publish | **Cần push bù** khi MQTT reconnect |
| `0x55` | `SLOT_PUBLISHED` | Đã publish thành công | Đánh dấu sẵn sàng để tái sử dụng |
| `0xEE` | `SLOT_DISCARD` | Bỏ qua (lỗi hoặc quá retry) | Ghi log lý do, skip khi replay |
| `0xFF` | `SLOT_ERASED` | Flash đã erase (chưa format) | Coi như `SLOT_FREE` |

### 2.3. Message Type Enum

| Giá trị | Tên | Topic MQTT tương ứng |
|---------|-----|---------------------|
| `0x01` | `MSG_TELEMETRY` | `charging/st/{mac}/post/{id}/tlm` |
| `0x02` | `MSG_EVENT` | `charging/st/{mac}/post/{id}/evt` |
| `0x03` | `MSG_SESSION_STATUS` | `charging/st/{mac}/post/{id}/status` |
| `0x04` | `MSG_GW_STATUS` | `charging/st/{mac}/gw_status` |
| `0x05` | `MSG_CMD_ACK` | `charging/st/{mac}/post/{id}/cmd_ack` |

### 2.4. Payload Data (48 bytes) — Format theo msg_type

#### MSG_TELEMETRY (48 bytes)
```
Offset  Size  Field              Đơn vị gốc (Modbus raw)
0x00    2     voltage            0.1V
0x02    2     current            0.01A
0x04    2     power              W
0x06    2     energy_hi          Wh (high word)
0x08    2     energy_lo          Wh (low word)
0x0A    2     temperature        0.1°C
0x0C    1     fsm_state          enum
0x0D    2     frequency          0.01Hz
0x0F    2     power_factor       0.001
0x11    2     session_energy     Wh
0x13    2     session_id         -
0x15    2     session_duration   s
0x17    1     connector_status   enum
0x18    2     alarm_flags        bitmask
0x1A    1     relay_status       bitmask
0x1B    6     meter_serial       BCD raw (3 regs × 2 bytes)
0x21    1     meter_valid        bool
0x22    14    _reserved          0x00 padding
```
**Tổng dùng:** 34 bytes / 48 bytes. 14 bytes dự phòng cho register mới trong tương lai.

#### MSG_EVENT (48 bytes)
```
Offset  Size  Field              Ghi chú
0x00    1     message_type       0=EVENT, 1=ALARM
0x01    1     event_code         Xem bảng enum
0x02    4     value              float IEEE754 (nhiệt độ/dòng tại thời điểm lỗi)
0x06    1     recovered_from     event_code cũ (0xFF = null / không áp dụng)
0x07    41    _reserved          0x00 padding
```

#### MSG_SESSION_STATUS (48 bytes)
```
Offset  Size  Field              Ghi chú
0x00    1     message_type       0
0x01    1     event_code         10=STARTED, 11=COMPLETED
0x02    2     session_id         uint16
0x04    4     start_kwh          uint32 (giá trị × 1000, vd 120550 = 120.550 kWh)
0x08    4     end_kwh            uint32 (× 1000, chỉ dùng khi event_code=11)
0x0C    4     total_consumed     uint32 (× 1000)
0x10    1     reason             enum (chỉ dùng khi event_code=11)
0x11    37    _reserved          0x00 padding
```

#### MSG_GW_STATUS (48 bytes)
```
Offset  Size  Field              Ghi chú
0x00    4     uptime             uint32 (giây)
0x04    4     free_heap          uint32 (bytes)
0x08    4     min_free_heap      uint32 (bytes)
0x0C    1     reset_reason       esp_reset_reason_t
0x0D    1     eth_connected      bool
0x0E    1     total_posts        uint8
0x0F    1     count_idle         uint8
0x10    1     count_charging     uint8
0x11    1     count_error        uint8
0x12    1     count_offline      uint8
0x13    35    _reserved          0x00 padding
```

#### MSG_CMD_ACK (48 bytes)
```
Offset  Size  Field              Ghi chú
0x00    16    cmd_name           ASCII null-terminated (vd "start_charge\0")
0x10    1     result             0=ok, 1=error
0x11    16    error_msg          ASCII null-terminated (vd "slave_offline\0")
0x21    27    _reserved          0x00 padding
```

---

## 3. Luồng Hoạt Động Store-and-Forward

### 3.1. Luồng Ghi (Write Path)

```
Modbus Poll xong → Cần publish TLM/EVT/STATUS
  │
  ├── MQTT Connected?
  │   ├── YES → Publish trực tiếp
  │   │         ├── Publish OK → Không ghi Flash (tiết kiệm write cycle)
  │   │         └── Publish FAIL → Chuyển sang nhánh NO ▼
  │   │
  │   └── NO → Serialize data thành block 64 bytes
  │             → Tìm slot: scan sync_flag == SLOT_FREE hoặc SLOT_PUBLISHED hoặc SLOT_ERASED
  │             → Ghi block vào slot, set sync_flag = SLOT_PENDING
  │             → Tăng global sequence counter
  │
  └── Queue đầy (>90% capacity)?
      → Scan block cũ nhất có sync_flag == SLOT_PUBLISHED → ghi đè (FIFO)
      → Nếu không có PUBLISHED → ghi đè PENDING cũ nhất (hy sinh bản tin cũ)
      → Log warning: "offline_queue: overflow, dropping oldest record seq=%u"
```

### 3.2. Luồng Replay (Push Bù khi MQTT Reconnect)

```
MQTT Connected Event (esp_mqtt_event_id_t = MQTT_EVENT_CONNECTED)
  │
  ├── Đợi 2 giây (ổn định kết nối, tránh burst flood Broker)
  │
  ├── Scan toàn bộ storage partition theo thứ tự sequence tăng dần
  │   └── Với mỗi block có sync_flag == SLOT_PENDING:
  │       ├── Reconstruct JSON payload từ binary data
  │       ├── Reconstruct topic string từ msg_type + slave_id + MAC
  │       ├── esp_mqtt_client_publish(topic, payload, qos, retain)
  │       │
  │       ├── Publish OK?
  │       │   ├── YES → Set sync_flag = SLOT_PUBLISHED
  │       │   └── NO  → retry_count++
  │       │             ├── retry_count < 5 → Skip, thử lại lần replay sau
  │       │             └── retry_count >= 5 → Set sync_flag = SLOT_DISCARD
  │       │                                   Log: "offline_queue: discard seq=%u after 5 retries"
  │       │
  │       └── Delay 50ms giữa mỗi record (tránh flood broker, tránh OOM)
  │
  └── Replay xong → Log: "offline_queue: replayed %u records, discarded %u"
```

### 3.3. Luồng Dọn dẹp (Garbage Collection)

```
Chu kỳ 5 phút (hoặc khi ghi gặp queue đầy):
  → Scan tất cả blocks
  → Đếm: free, pending, published, discard
  → Nếu published + discard > 50% tổng capacity:
      → Batch set sync_flag = SLOT_FREE cho tất cả PUBLISHED và DISCARD
  → Log: "offline_queue: gc complete, free=%u pending=%u"
```

---

## 4. Cơ chế Phòng chống Lỗi & Crash

### 4.1. Mất mạng / MQTT Disconnect — KHÔNG được treo

| Tình huống | Xử lý | Ghi chú |
|------------|--------|---------|
| Ethernet cable rút | `ETH_EVENT_DISCONNECTED` → set flag `eth_connected=false`. Modbus polling **vẫn chạy bình thường**. Bản tin chuyển sang offline queue. | LED chớp nhanh |
| MQTT broker không phản hồi | `esp_mqtt_client` có built-in reconnect (5s interval). Không block task khác. | Dùng non-blocking API |
| MQTT publish timeout | `esp_mqtt_client_publish()` return `msg_id < 0` → ghi vào offline queue, **KHÔNG retry ngay** (tránh vòng lặp vô hạn). | Set retry timer 30s |
| DNS resolve fail | Static IP broker → không cần DNS. Nếu dùng domain → timeout 5s, fallback IP NVS. | Config backup IP trong NVS |
| TLS handshake fail | Log error, retry sau 30s. Không crash. Có thể fallback non-TLS nếu config cho phép. | `CONFIG_MBEDTLS_SSL_OUT_CONTENT_LEN=4096` tiết kiệm RAM |
| Wi-Fi AP bật nhưng không có client | AP tự tắt sau 10 phút. Không tiêu tốn tài nguyên. | Timer callback |

**Quy tắc vàng:**
```c
// KHÔNG BAO GIỜ block trong MQTT task
// ĐÚNG:
int msg_id = esp_mqtt_client_publish(client, topic, payload, 0, qos, retain);
if (msg_id < 0) {
    offline_queue_push(msg_type, slave_id, data, sizeof(data));
    // Tiếp tục xử lý bản tin tiếp theo, KHÔNG retry
}

// SAI (gây treo):
// while (mqtt_publish(topic, payload) != OK) { vTaskDelay(1000); }
```

### 4.2. Server gửi dữ liệu rác — Phòng vệ JSON Parser

| Bad-case từ Server | Phòng vệ | Code pattern |
|---------------------|----------|--------------|
| Payload rỗng `""` hoặc `null` | Check `data_len == 0` trước khi parse | `if (!data \|\| data_len == 0) return;` |
| JSON không hợp lệ `{broken` | `cJSON_Parse()` return `NULL` → log error, skip | `cJSON *root = cJSON_Parse(data); if (!root) { ESP_LOGW(TAG, "bad json"); return; }` |
| Field `cmd` bị null | Check trước khi `strcmp()` | `cJSON *cmd = cJSON_GetObjectItem(root, "cmd"); if (!cJSON_IsString(cmd)) goto cleanup;` |
| Field `params` bị thiếu | Dùng default values | `int energy_limit = 0; cJSON *p = cJSON_GetObjectItem(root, "params"); if (p) { ... }` |
| Giá trị number ngoài range | Clamp trước khi sử dụng | `int val = CLAMP(item->valueint, 0, 65535);` |
| Timestamp = 0 hoặc rất cũ | Bỏ qua bản tin quá cũ (> 5 phút) | `if (abs(now - cmd_ts) > 300) { ESP_LOGW(TAG, "stale cmd"); goto cleanup; }` |
| Topic không khớp post_id | Validate slave_id range | `if (post_id < 1 \|\| post_id > total_posts) return;` |
| Payload quá lớn (> 2KB) | Giới hạn buffer | `CONFIG_MQTT_BUFFER_SIZE=2048`, check `data_len < MAX_PAYLOAD` |
| Flood commands (30 cmd/s) | Rate limiter | `if (millis() - last_cmd_time < 200) return; // min 200ms between commands` |
| cmd = `"gateway_reboot"` liên tục | Cooldown 60s | `if (millis() - last_reboot_req < 60000) return;` |

**Template xử lý Command an toàn:**
```c
static void mqtt_handle_command(const char *topic, const char *data, int data_len)
{
    // Guard 1: Null/Empty check
    if (!data || data_len == 0 || data_len > 2048) {
        ESP_LOGW(TAG, "cmd: invalid payload len=%d", data_len);
        return;
    }

    // Guard 2: JSON parse
    cJSON *root = cJSON_Parse(data);
    if (!root) {
        ESP_LOGW(TAG, "cmd: json parse failed");
        return;
    }

    // Guard 3: Required field check
    cJSON *cmd_field = cJSON_GetObjectItem(root, "cmd");
    if (!cJSON_IsString(cmd_field) || cmd_field->valuestring == NULL) {
        ESP_LOGW(TAG, "cmd: missing 'cmd' field");
        goto cleanup;
    }

    // Guard 4: Stale message check
    cJSON *ts_field = cJSON_GetObjectItem(root, "timestamp");
    if (cJSON_IsNumber(ts_field)) {
        uint32_t now = time_get_unix();
        if (now > 1000000 && abs((int)(now - (uint32_t)ts_field->valuedouble)) > 300) {
            ESP_LOGW(TAG, "cmd: stale message, age=%ds", abs((int)(now - (uint32_t)ts_field->valuedouble)));
            goto cleanup;
        }
    }

    // Guard 5: Rate limiter
    static uint32_t last_cmd_ms = 0;
    if (xTaskGetTickCount() * portTICK_PERIOD_MS - last_cmd_ms < 200) {
        ESP_LOGW(TAG, "cmd: rate limited");
        goto cleanup;
    }
    last_cmd_ms = xTaskGetTickCount() * portTICK_PERIOD_MS;

    // Guard 6: Extract slave_id from topic, validate range
    uint8_t slave_id = parse_slave_id_from_topic(topic);
    if (slave_id > 0 && (slave_id < 1 || slave_id > config_get_total_posts())) {
        ESP_LOGW(TAG, "cmd: invalid slave_id=%d", slave_id);
        goto cleanup;
    }

    // --- Safe to process ---
    const char *cmd = cmd_field->valuestring;
    cJSON *params = cJSON_GetObjectItem(root, "params"); // May be NULL, that's OK

    if (strcmp(cmd, "start_charge") == 0) {
        // Extract optional param with default
        int energy_limit = 0;
        if (params && cJSON_IsNumber(cJSON_GetObjectItem(params, "session_energy_limit"))) {
            energy_limit = CLAMP(cJSON_GetObjectItem(params, "session_energy_limit")->valueint, 0, 65535);
        }
        // Execute...
    }
    // ... other commands ...

cleanup:
    cJSON_Delete(root);  // LUÔN LUÔN free, tránh memory leak
}
```

### 4.3. Modbus Slave không phản hồi — Graceful Degradation

| Tình huống | Xử lý |
|------------|--------|
| Slave timeout 1 lần | Tăng `timeout_count++`. Retry lần tiếp trong chu kỳ polling sau. |
| Slave timeout 3 lần liên tiếp | Đánh dấu `charger_states[id].online = false`. Set FSM = `OFFLINE (255)`. Post event `EVT_COMM_FAIL`. |
| Slave recovery sau offline | Reset `timeout_count = 0`, `online = true`. Post event `EVT_NORMAL_STATE`. |
| CRC error | Tăng `crc_errors++`. Bỏ qua frame, đợi respond lần sau. KHÔNG crash. |
| UART buffer overflow | `uart_flush()` trước mỗi transaction. Set RX buffer đủ lớn (256 bytes). |
| Tất cả Slaves offline | Gateway vẫn chạy. gw_status vẫn publish (all offline). Web dashboard vẫn truy cập được. |

### 4.4. Flash/LittleFS Errors

| Tình huống | Xử lý |
|------------|--------|
| LittleFS mount fail | Log error. Disable offline queue. Gateway vẫn hoạt động realtime (chỉ mất store-and-forward). |
| Write fail (bad sector) | Skip block, try next slot. Log warning. |
| Read corrupt data (magic != 0xBEEF) | Skip block, set `sync_flag = SLOT_FREE`. |
| Partition full (>95%) | Trigger garbage collection trước khi ghi. |
| Power loss giữa lúc ghi | Block có `magic != 0xBEEF` hoặc `sync_flag` không hợp lệ → auto discard khi scan. |

### 4.5. RAM / Heap Exhaustion

```c
// Kiểm tra heap trước khi cấp phát lớn
#define SAFE_HEAP_THRESHOLD  (20 * 1024)  // 20KB minimum

char *json_buf = NULL;
if (esp_get_free_heap_size() > SAFE_HEAP_THRESHOLD + 1024) {
    json_buf = cJSON_PrintUnformatted(root);
}
if (!json_buf) {
    ESP_LOGE(TAG, "OOM: skip publish, free_heap=%u", esp_get_free_heap_size());
    // Ghi binary block vào offline queue thay vì crash
    offline_queue_push(msg_type, slave_id, &compact_data, sizeof(compact_data));
    goto cleanup;
}
// ... publish ...
cJSON_free(json_buf);  // LUÔN free
```

---

## 5. API Functions — Offline Queue Module

```c
// offline_queue.h

/// Khởi tạo: mount LittleFS partition "storage", scan records hiện có
esp_err_t offline_queue_init(void);

/// Ghi 1 record 64 bytes vào slot trống
/// @param msg_type  MSG_TELEMETRY, MSG_EVENT, ...
/// @param slave_id  Modbus slave ID (0 = gateway-level)
/// @param payload   Con trỏ đến binary payload (48 bytes)
/// @param payload_len  Phải == 48
/// @return ESP_OK hoặc ESP_ERR_NO_MEM nếu queue đầy và GC không giải phóng được
esp_err_t offline_queue_push(uint8_t msg_type, uint8_t slave_id,
                              const void *payload, size_t payload_len);

/// Replay tất cả SLOT_PENDING theo thứ tự sequence
/// Gọi khi MQTT_EVENT_CONNECTED
/// @param max_records  Giới hạn số record replay mỗi lần (tránh block task lâu)
/// @return Số record đã publish thành công
uint32_t offline_queue_replay(uint32_t max_records);

/// Garbage collection: free các slot PUBLISHED và DISCARD
/// @return Số slot đã giải phóng
uint32_t offline_queue_gc(void);

/// Thống kê
typedef struct {
    uint32_t total_slots;      // Tổng capacity
    uint32_t free_slots;       // SLOT_FREE + SLOT_ERASED
    uint32_t pending_slots;    // SLOT_PENDING (cần push bù)
    uint32_t published_slots;  // SLOT_PUBLISHED (đã publish OK)
    uint32_t discard_slots;    // SLOT_DISCARD (bỏ qua)
    uint32_t used_bytes;       // pending × 64
    uint32_t total_bytes;      // partition size
} offline_queue_stats_t;

esp_err_t offline_queue_get_stats(offline_queue_stats_t *stats);
```

---

## 6. Lưu trữ khác trong Storage Partition

Ngoài offline queue, phân vùng `storage` còn chứa:

| Thư mục/File | Mô tả | Kích thước ước lượng |
|--------------|--------|---------------------|
| `/queue/` | Offline queue blocks (file dạng `q_000000.bin` → `q_028671.bin`) | ~1.6MB (chiếm phần lớn) |
| `/config_backup.json` | Bản sao NVS config (IP, MQTT, total_posts) phòng NVS corrupt | ~1KB |
| `/session_cache.bin` | Cache session đang chạy (session_id, start_kwh) phòng mất điện giữa phiên sạc | ~64 bytes × MAX_POSTS |
| `/ota_state.json` | Trạng thái OTA đang dở (url, progress, partition) phòng mất điện giữa OTA | ~256 bytes |

---

## 7. Bài học Thực chiến từ GELEX Gateway V2 (Production Bugs)

> [!CAUTION]
> Các lỗi bên dưới đều đã **xảy ra thực tế trên sản phẩm thương mại** (GELEX DLMS Gateway ESP32-S2). Áp dụng ngay để tránh lặp lại.

### 7.1. Boot-Loop Flash Wear-out Protection

**Lỗi:** Gateway liên tục crash ngay sau boot (ví dụ: firmware OTA lỗi). Mỗi lần crash ghi NVS `reset_count++`. Hàng ngàn chu kỳ ghi → mòn sector NVS.

**Giải pháp:**
```c
// Trong app_main(), đọc uptime lần boot trước
// Nếu uptime < 30s cho 5 lần reboot liên tiếp → DỪNG ghi NVS, vào Safe Mode
#define BOOT_LOOP_MAX       5
#define BOOT_LOOP_MIN_UP_S  30

void app_main(void) {
    uint8_t rapid_boot_count = nvs_read_u8("rapid_boots");
    uint32_t last_uptime = nvs_read_u32("last_uptime");

    if (last_uptime < BOOT_LOOP_MIN_UP_S) {
        rapid_boot_count++;
    } else {
        rapid_boot_count = 0;
    }

    if (rapid_boot_count >= BOOT_LOOP_MAX) {
        // SAFE MODE: chỉ bật Web Dashboard, không chạy MQTT/Modbus
        ESP_LOGE(TAG, "BOOT LOOP DETECTED! Entering Safe Mode...");
        led_pattern_sos();  // Chớp SOS
        webserver_init();   // Chỉ chạy Web để user fix config
        return;             // Không khởi tạo gì thêm
    }

    nvs_write_u8("rapid_boots", rapid_boot_count);
    // ... khởi tạo bình thường ...

    // Reset counter sau khi chạy ổn 60s
    vTaskDelay(pdMS_TO_TICKS(60000));
    nvs_write_u8("rapid_boots", 0);
    nvs_write_u32("last_uptime", esp_timer_get_time() / 1000000);
}
```

### 7.2. KHÔNG xử lý nặng trong `esp_timer` callback

**Lỗi:** Gọi `cJSON_Print()` hoặc `esp_http_client()` trực tiếp trong `esp_timer` callback → Stack overflow (esp_timer task chỉ có 4352 bytes stack).

**Giải pháp:** `esp_timer` callback chỉ được gọi `esp_event_post()` (O(1), tốn < 100 bytes stack). Event handler ở System Event Task (8192 bytes stack) sẽ xử lý nặng.

```c
// SAI (crash):
void timer_cb(void *arg) {
    char *json = cJSON_PrintUnformatted(root);  // 💥 Stack overflow!
    esp_mqtt_client_publish(client, topic, json, 0, 1, 1);
}

// ĐÚNG:
void timer_cb(void *arg) {
    esp_event_post(APP_EVENT, EVT_PUBLISH_TLM, NULL, 0, 0);  // ✅ O(1)
}

void on_publish_tlm(void *args, esp_event_base_t base, int32_t id, void *data) {
    // Chạy trong System Event Task (stack 8192), an toàn
    char *json = cJSON_PrintUnformatted(root);
    esp_mqtt_client_publish(client, topic, json, 0, 1, 1);
    cJSON_free(json);
}
```

### 7.3. MQTT QoS 1 Blocking Risk

**Lỗi:** `esp_mqtt_client_publish()` với QoS 1 chờ ACK từ broker. Nếu mạng yếu, timeout có thể kéo dài 30-120s → block task → Task WDT panic.

**Giải pháp:**
- Dùng QoS 0 cho TLM (mất 1 bản tin TLM không sao, có bản tin kế tiếp).
- Dùng QoS 1 chỉ cho EVT và STATUS (quan trọng, không được mất).
- Set `CONFIG_MQTT_TIMEOUT_MS=5000` (timeout 5s, không chờ quá lâu).
- Isolate publish task: tách riêng task publish, feed WDT trước mỗi publish.

### 7.4. NVS Log Flooding Prevention

**Lỗi:** Đồng hồ Modbus mất kết nối → mỗi giây ghi 1 dòng "READ_FAIL" vào NVS/SPIFFS → đầy partition trong vài giờ.

**Giải pháp:** Chỉ ghi log lỗi theo **interval** (ví dụ: mỗi 5 phút ghi 1 lần), không ghi mỗi lần poll thất bại.

```c
static uint32_t last_fail_log_ms = 0;
#define FAIL_LOG_INTERVAL_MS  (5 * 60 * 1000)  // 5 phút

if (modbus_read_failed) {
    if (xTaskGetTickCount() * portTICK_PERIOD_MS - last_fail_log_ms > FAIL_LOG_INTERVAL_MS) {
        system_log_crash(REASON_MODBUS_FAIL, time_get_unix());
        last_fail_log_ms = xTaskGetTickCount() * portTICK_PERIOD_MS;
    }
}
```

### 7.5. LittleFS Circular Cleanup — Kiểm tra đúng Extension

**Lỗi:** Hàm cleanup tìm file `.dat` nhưng data ghi ra file `.bin` → cleanup không bao giờ xóa được file cũ → partition đầy → write fail.

**Giải pháp:** Thống nhất extension cho toàn bộ storage module. Dùng constant:
```c
#define QUEUE_FILE_EXT  ".bin"  // Single Source of Truth
```

### 7.6. Bounds Checking cho mọi Protocol Parser

**Lỗi:** Parser DLMS/Modbus tìm thấy header byte nhưng truy cập `data[i+8]` mà không kiểm tra `i+8 < len` → đọc ngoài vùng nhớ → crash hoặc data rác.

**Giải pháp cho Modbus RTU:**
```c
// Khi parse FC04 response:
// Response format: [slave_id][fc][byte_count][data...][crc_lo][crc_hi]
esp_err_t modbus_parse_response(const uint8_t *buf, size_t len,
                                 uint16_t *regs, size_t num_regs)
{
    // Guard 1: minimum frame length
    if (len < 5) return ESP_ERR_INVALID_SIZE;

    // Guard 2: byte_count consistency
    uint8_t byte_count = buf[2];
    if (byte_count != num_regs * 2) return ESP_ERR_INVALID_RESPONSE;
    if (3 + byte_count + 2 > len) return ESP_ERR_INVALID_SIZE;  // +2 for CRC

    // Guard 3: CRC check TRƯỚC khi parse data
    uint16_t crc = modbus_crc16(buf, len - 2);
    if (crc != (buf[len-2] | (buf[len-1] << 8))) return ESP_ERR_INVALID_CRC;

    // Safe to parse
    for (size_t i = 0; i < num_regs && (3 + i*2 + 1) < len; i++) {
        regs[i] = (buf[3 + i*2] << 8) | buf[3 + i*2 + 1];
    }
    return ESP_OK;
}
```

### 7.7. EMI và Brown-out trong Tủ Điện Công Nghiệp

**Lỗi:** Contactor/Relay đóng tạo xung điện từ → nhiễu UART RS485 → CRC error hoặc "ghost" start bit. Brown-out nếu LDO 3.3V yếu.

**Giải pháp:**
- `uart_set_pin()` với `GPIO_PULLUP_ONLY` trên RX pin để giữ line ổn định khi idle.
- `uart_flush_input()` **trước mỗi transaction** Modbus.
- Thêm tụ lọc 1000µF trên rail 5V đầu vào board.
- `CONFIG_ESP_BROWNOUT_LEVEL=6` (2.44V threshold thay vì mặc định 2.80V để tránh reset không cần thiết).

### 7.8. Chunked HTTP Response cho JSON lớn

**Lỗi:** `httpd_resp_sendstr()` với JSON > 2KB trên ESP32 gây OOM vì phải copy toàn bộ string vào HTTP buffer.

**Giải pháp:**
```c
// Dùng chunked response:
httpd_resp_set_type(req, "application/json");
httpd_resp_sendstr_chunk(req, "{\"posts\":[");
for (int i = 0; i < total_posts; i++) {
    char buf[256];
    format_post_json(i, buf, sizeof(buf));  // Stack buffer, không malloc
    httpd_resp_sendstr_chunk(req, buf);
    if (i < total_posts - 1) httpd_resp_sendstr_chunk(req, ",");
}
httpd_resp_sendstr_chunk(req, "]}");
httpd_resp_sendstr_chunk(req, NULL);  // Kết thúc chunked transfer
```

### 7.9. POST Config Buffer Sizing

**Lỗi:** TLS certificate trong POST `/api/config` có thể > 1KB. Buffer 1024 bytes mặc định bị cắt ngắn JSON → parse fail → mất config.

**Giải pháp:**
```c
// sdkconfig.defaults:
CONFIG_HTTPD_MAX_REQ_HDR_LEN=1024
CONFIG_HTTPD_MAX_URI_LEN=1024

// Trong web_ui handler, đọc body theo chunk:
#define MAX_POST_SIZE  4096
char *buf = malloc(MAX_POST_SIZE);
if (!buf) { httpd_resp_send_500(req); return ESP_FAIL; }

int received = httpd_req_recv(req, buf, MAX_POST_SIZE - 1);
if (received <= 0) { free(buf); return ESP_FAIL; }
buf[received] = '\0';
// ... parse ...
free(buf);
```

---

## 8. sdkconfig Hardening (Bổ sung từ kinh nghiệm Production)

```ini
# === Baseline (đã có) ===
CONFIG_PARTITION_TABLE_CUSTOM=y
CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions.csv"
CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y
CONFIG_ESP_MAIN_TASK_STACK_SIZE=8192
CONFIG_HTTPD_WS_SUPPORT=y
CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y
CONFIG_ESP_TASK_WDT_PANIC=y
CONFIG_ESP_COREDUMP_ENABLE_TO_FLASH=y
CONFIG_SPIRAM_USE_MALLOC=y

# === Hardening (mới, từ GELEX production) ===
# MQTT timeout ngắn để không block task lâu
CONFIG_MQTT_TRANSPORT_SSL=y
CONFIG_MQTT_TASK_STACK_SIZE=8192
# CONFIG_MQTT_TIMEOUT_MS=5000           # Tự set trong code

# TLS memory optimization (GELEX lesson: giảm RAM 12KB)
CONFIG_MBEDTLS_ASYMMETRIC_CONTENT_LEN=y
CONFIG_MBEDTLS_SSL_IN_CONTENT_LEN=16384
CONFIG_MBEDTLS_SSL_OUT_CONTENT_LEN=4096
CONFIG_MBEDTLS_CERTIFICATE_BUNDLE=y

# HTTP server buffers (GELEX lesson: POST config > 1KB)
CONFIG_HTTPD_MAX_REQ_HDR_LEN=1024
CONFIG_HTTPD_MAX_URI_LEN=1024

# Brown-out protection (GELEX lesson: EMI từ contactor)
# CONFIG_ESP_BROWNOUT_DET_LVL_SEL_6=y  # 2.44V thay vì 2.80V

# System event loop stack (GELEX lesson: esp_timer stack overflow fix)
CONFIG_ESP_SYSTEM_EVENT_TASK_STACK_SIZE=8192

# Task WDT timeout (production: 120s để tránh false positive)
CONFIG_ESP_TASK_WDT_TIMEOUT_S=120

# UART buffer cho Modbus (GELEX lesson: EMI noise)
# Đặt trong code: uart_driver_install(UART_NUM_1, 256, 256, ...)

# LittleFS thay SPIFFS (reliability cao hơn cho power-loss)
# Dùng component esp_littlefs từ Espressif registry
```

