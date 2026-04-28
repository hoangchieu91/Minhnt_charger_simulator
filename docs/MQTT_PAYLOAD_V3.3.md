# CẤU TRÚC BẢN TIN MQTT GIAO TIẾP TRẠM SẠC (V3.4)

Tài liệu này mô tả chi tiết các Payload JSON thực tế, bao gồm luồng giao tiếp Server ↔ ESP32 Gateway ↔ Trụ Sạc (Modbus RTU). 

**Quy ước chung:**
- `{mac}`: Địa chỉ MAC của ESP32 (Đóng vai trò Gateway).
- `{post_id}`: Địa chỉ Slave Modbus của từng điểm sạc (1, 2, 3...).
- Tất cả các bản tin sự kiện, trạng thái đều phải được thiết lập cờ **RETAIN = true**.
- FSM State enum tuân thủ **MODBUS_REGISTER_MAP.md** (nguồn sự thật duy nhất).

---

## 1. Bản tin Trạng thái Gateway & Thống kê điểm sạc
**Topic:** `charging/st/{mac}/gw_status`  
**Hướng:** ESP32 (Gateway) -> Server  
**Chu kỳ:** Định kỳ (1 phút / lần) hoặc cập nhật ngay khi một trạm con chuyển trạng thái.  
**Mục đích:** Báo cáo sức khỏe của ESP32 và tổng hợp thống kê toàn bộ các post đang quản lý.

```json
{
  "timestamp": 1711284000,
  "uptime": 3600,
  "fw_version": "1.2.0",
  "free_heap": 45320,
  "min_free_heap": 32768,
  "reset_reason": 1,
  "eth_connected": true,
  "ip_addr": "192.168.1.100",
  "wifi_rssi": null,
  "stats": {
    "total_posts": 10,
    "idle": 5,
    "charging": 3,
    "error": 1,
    "offline": 1
  },
  "posts_state": [
    {"id": 1, "state": 3},
    {"id": 2, "state": 1},
    {"id": 3, "state": 5}
  ]
}
```

**Chú thích fields mới:**
- `fw_version`: Phiên bản firmware Gateway hiện tại (cho OTA check).
- `free_heap` / `min_free_heap`: Bộ nhớ khả dụng (bytes) — phát hiện rò rỉ bộ nhớ.
- `reset_reason`: Lý do reset gần nhất từ `esp_reset_reason()` (1=PowerOn, 3=SW, 4=Panic, 5=IntWDT, 6=TaskWDT...).
- `eth_connected`: `true` nếu đang dùng Ethernet, `false` nếu đang dùng Wi-Fi AP.

---

## 2. Bản tin Điều khiển (Command)
**Topic:** `charging/st/{mac}/post/{post_id}/cmd`  
**Hướng:** Server -> ESP32  

### 2.1. Lệnh Bắt đầu sạc
```json
{
  "cmd": "start_charge",
  "params": {
    "min_current": 0.20,
    "max_coin_limit": 500.0,
    "session_energy_limit": 5000
  },
  "timestamp": 1711284500
}
```
> **MỚI:** `session_energy_limit` (Wh) — Gateway ghi vào HR `0x010B` trước khi kích FC05 `start_charge`. Giá trị 0 = không giới hạn.

### 2.2. Lệnh Dừng sạc
```json
{
  "cmd": "stop_charge",
  "params": {
    "reason": 3
  },
  "timestamp": 1711285000
}
```

### 2.3. Lệnh Mở khóa cửa (Bảo trì)
```json
{
  "cmd": "unlock_door",
  "params": {
    "duration_ms": 5000
  },
  "timestamp": 1711285050
}
```

### 2.4. Lệnh Xóa lỗi (Clear Error)
```json
{
  "cmd": "clear_error",
  "timestamp": 1711285055
}
```

### 2.5. Lệnh Khởi động lại Gateway
**Topic:** `charging/st/{mac}/cmd` (Đi thẳng vào Gateway thay vì vào từng Post)
```json
{
  "cmd": "gateway_reboot",
  "timestamp": 1711285060
}
```

### 2.6. Lệnh Cập nhật Firmware OTA (MỚI)
**Topic:** `charging/st/{mac}/cmd`
```json
{
  "cmd": "ota_update",
  "params": {
    "url": "https://nxchieu.duckdns.org/ota/firmware.bin",
    "version": "1.3.0"
  },
  "timestamp": 1711285070
}
```

### 2.7. Lệnh Cấu hình Giới hạn Dòng (Dynamic Load Balancing — MỚI)
**Topic:** `charging/st/{mac}/post/{post_id}/cmd`
```json
{
  "cmd": "set_current_limit",
  "params": {
    "current_limit": 16.00
  },
  "timestamp": 1711285080
}
```
> Gateway ghi FC06 vào HR `0x010A` với giá trị `current_limit * 100` (đơn vị 0.01A).

---

## 3. Bản tin Phản hồi Lệnh (Command ACK — MỚI)
**Topic:** `charging/st/{mac}/post/{post_id}/cmd_ack`  
**Hướng:** ESP32 -> Server  
**Mục đích:** Xác nhận Gateway đã nhận và thực thi lệnh thành công hay thất bại.

```json
{
  "cmd": "start_charge",
  "result": "ok",
  "error_msg": null,
  "timestamp": 1711284510
}
```

**Các trường hợp lỗi:**
```json
{
  "cmd": "start_charge",
  "result": "error",
  "error_msg": "slave_offline",
  "timestamp": 1711284510
}
```

| `error_msg` | Mô tả |
|-------------|--------|
| `null` | Thành công |
| `slave_offline` | Slave không phản hồi Modbus |
| `modbus_timeout` | Timeout khi ghi FC05/FC06 |
| `already_charging` | Trạm đang ở trạng thái CHARGING |
| `invalid_state` | FSM state không cho phép thực hiện lệnh này |
| `slave_error` | Slave đang ở trạng thái ERROR |

---

## 4. Bản tin Telemetry định kỳ (TLM)
**Topic:** `charging/st/{mac}/post/{post_id}/tlm`  
**Hướng:** ESP32 -> Server  
**Chu kỳ:** 30s khi đang sạc, 60s khi nhàn rỗi, hoặc tiêu thụ được 0.1kWh.

```json
{
  "state": 3,
  "voltage": 225.4,
  "current": 12.85,
  "power": 2896.3,
  "frequency": 50.02,
  "power_factor": 0.952,
  "energy_total": 121.250,
  "energy_session": 0.700,
  "temperature": 45.5,
  "session_id": 142,
  "session_duration": 1830,
  "connector_status": 2,
  "meter_serial": "012345678912",
  "alarm_flags": 0,
  "relay_status": 5,
  "timestamp": 1711284600
}
```

**Chú thích fields mới so với V3.3:**
- `frequency`: Từ register `0x0026` (đơn vị 0.01Hz → chia 100).
- `power_factor`: Từ register `0x0027` (đơn vị 0.001 → chia 1000).
- `session_id`: Từ register `0x0029` — liên kết chính xác START↔STOP.
- `session_duration`: Từ register `0x0019` (giây).
- `connector_status`: Từ register `0x002B` (0=Unplugged, 1=Plugged, 2=Locked).
- `alarm_flags`: Từ register `0x0018` — bitmask đầy đủ thay vì chỉ relay.
- `relay_status`: Từ register `0x0007`.

> [!NOTE]
> FSM `state` giá trị tuân thủ bảng `FSM State` trong `MODBUS_REGISTER_MAP.md`. Giá trị `255` (OFFLINE) do Gateway tự gán khi Slave mất kết nối Modbus, không phải giá trị từ Slave.

---

## 5. Bản tin Sự kiện Sạc (Status)
**Topic:** `charging/st/{mac}/post/{post_id}/status`  
**Hướng:** ESP32 -> Server  

### 5.1. Sự kiện Bắt đầu (Chốt số công tơ đầu kỳ)
```json
{
  "message_type": 0,    
  "event_code": 10,
  "session_id": 142,
  "start_kwh": 120.550,
  "timestamp": 1711284515 
}
```

### 5.2. Sự kiện Kết thúc (Chốt số công tơ cuối kỳ)
```json
{
  "message_type": 0,    
  "event_code": 11,
  "session_id": 142,
  "start_kwh": 120.550, 
  "end_kwh": 125.750,
  "total_consumed": 5.200, 
  "reason": 3,
  "timestamp": 1711285005 
}
```

> **MỚI:** `session_id` — liên kết phiên START↔STOP, tránh mất dữ liệu khi Gateway restart giữa phiên.

---

## 6. Bản tin Cảnh báo Sự cố & Khôi phục (EVT)
**Topic:** `charging/st/{mac}/post/{post_id}/evt`  
**Hướng:** ESP32 -> Server  

```json
{
  "message_type": 1,
  "event_code": 1,
  "value": 78.5,
  "recovered_from": null,
  "timestamp": 1711285100 
}
```

---

## 7. Bản tin OTA Progress (MỚI)
**Topic:** `charging/st/{mac}/ota_progress`  
**Hướng:** ESP32 -> Server  

```json
{
  "status": "downloading",
  "progress": 45,
  "version": "1.3.0",
  "error": null,
  "timestamp": 1711286000
}
```

| `status` | Mô tả |
|----------|--------|
| `downloading` | Đang tải firmware |
| `verifying` | Kiểm tra checksum |
| `flashing` | Ghi vào partition OTA |
| `rebooting` | Khởi động lại vào firmware mới |
| `success` | OTA thành công, firmware mới đang chạy |
| `rollback` | Firmware mới crash, đã rollback về bản cũ |
| `failed` | OTA thất bại (xem field `error`) |

---

## 8. Phụ lục: Bảng tra cứu Enum

### 8.1. Thuộc tính `cmd` (Lệnh từ Server)
| Tên lệnh | Ý nghĩa | Hành vi hệ thống |
|----------|---------|------------------|
| `start_charge` | Bắt đầu sạc | Set session_energy_limit → FC05 Coil 0x0000 |
| `stop_charge` | Dừng sạc | FC05 Coil 0x0001 → phát SESSION_COMPLETED |
| `clear_error` | Xóa lỗi | FC05 Coil 0x0003 → FSM reset |
| `unlock_door` | Mở cửa tủ | FC05 Coil 0x0002 → mở rơ le khóa |
| `gateway_reboot` | Khởi động lại | esp_restart() |
| `ota_update` | Cập nhật FW | Download → flash → reboot |
| `set_current_limit` | Set dòng max | FC06 HR 0x010A |

### 8.2. Thuộc tính `state` (Trạng thái trụ sạc)

> [!WARNING]
> Bảng này PHẢI đồng nhất với bảng FSM State trong `MODBUS_REGISTER_MAP.md`.

| Mã | Tên trạng thái | Mô tả |
|----|----------------|-------|
| 0 | `INIT` | Khởi tạo hệ thống, chưa sẵn sàng |
| 1 | `IDLE` | Rảnh, sẵn sàng nhận lệnh sạc |
| 2 | `STANDBY` | Chờ cắm súng sạc / xác nhận |
| 3 | `CHARGING` | Relay đóng, đang cấp nguồn |
| 4 | `FINISH` | Hoàn tất phiên sạc, chờ phản hồi |
| 5 | `ERROR` | Lỗi khẩn cấp (Hardware, nhiệt độ, Modbus) |
| 255 | `OFFLINE` | *(Chỉ Gateway)* Mất kết nối Modbus với điểm sạc |

### 8.3. Thuộc tính `event_code` (Mã sự kiện / báo lỗi)
| Mã | Phân loại | Tên sự kiện | Điều kiện kích hoạt |
|----|-----------|-------------|---------------------|
| **1** | ALARM | `CRITICAL_OVERHEAT` | Nhiệt độ NTC > 75°C |
| **2** | ALARM | `HIGH_TEMP_WARNING` | Nhiệt độ NTC > 45°C |
| **3** | ALARM | `DOOR_OPEN_ALARM` | Cửa mở trái phép |
| **4** | ALARM | `METER_OFFLINE` | Mất DLT645 |
| **5** | ALARM | `RELAY_STUCK_FAULT` | Dòng > 0.1A khi IDLE |
| **6** | ALARM | `COMM_FAIL` | Mất Modbus ESP32↔Slave |
| **7** | ALARM | `GROUND_FAULT` | Rò dòng ra vỏ (IEC 61851) |
| **8** | ALARM | `OVERCURRENT` | Dòng vượt current_limit |
| **10** | EVENT | `CHARGING_STARTED` | Relay đóng + dòng khởi sinh |
| **11** | EVENT | `SESSION_COMPLETED` | Phiên sạc hoàn tất |
| **12** | EVENT | `NORMAL_STATE` | Sự cố khôi phục |

### 8.4. Thuộc tính `reason` (Lý do dừng sạc)
| Mã | Tên lý do | Chi tiết |
|----|-----------|----------|
| 1 | `FINISHED_AUTO` | Dòng tiêu thụ giảm → xe đầy |
| 2 | `REMOTE_STOP_USER` | Người dùng nhấn Dừng trên App |
| 3 | `REMOTE_STOP_OUT_OF_COIN` | Hết tiền / coin từ Server |
| 4 | `SAFETY_ALARM_STOP` | Lỗi nhiệt độ, điện áp, rò điện |
| **5** | **`SESSION_ENERGY_EXCEEDED`** | **Đạt giới hạn kWh/phiên** |
| **6** | **`OVERCURRENT_STOP`** | **Dòng vượt ngưỡng current_limit** |

---

## 9. Yêu cầu Cấu hình Network & Local Web Dashboard (ESP32)

### 9.1. Chuẩn kết nối mạng (Ethernet-First)
- **Hardwire Network:** Sử dụng kết nối cáp mạng LAN thông qua module PHY Ethernet (LAN8742A qua RMII). Tuyệt đối **KHÔNG dùng Wi-Fi** làm kết nối chính.
- **Store-and-Forward:** Khi mất mạng, ESP32 vẫn duy trì Modbus bình thường và **lưu toàn bộ event/telemetry vào phân vùng `storage`** (JSON queue, FIFO max 500KB) để replay khi khôi phục.
- **Bảo mật AP:** Wi-Fi AP (`CHARGER_GW_MAC`) **CHỈ kích hoạt bằng nút nhấn vật lý** (giữ GPIO34 trong 5s) để chống xâm nhập.

### 9.2. Giao diện Web Dashboard Quản trị nội bộ (Local Web UI)
ESP32 chạy HTTP Server trên Port 80 + WebSocket `/ws` cho realtime data push.

**Các thành phần trang Dashboard bắt buộc:**
1. **Trang Giám sát (Overview):** Realtime qua WebSocket — V, A, W, kWh, Nhiệt độ, FSM State.
2. **Trang Cấu hình (Network & MQTT Config):** IP tĩnh, Gateway, MQTT Host/Port/User/Pass, TLS Cert upload.
3. **Trang Quản lý Modbus:** `total_posts`, Polling rate, Start ID.
4. **Trang Gỡ lỗi (Diagnostics):** Manual Override, Crash Log viewer, OTA trigger, System health.
