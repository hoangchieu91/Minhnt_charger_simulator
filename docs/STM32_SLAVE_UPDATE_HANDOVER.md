# 📋 BÀN GIAO YÊU CẦU CẬP NHẬT — STM32 Modbus RTU Slave (Rev 2.0)

**Dự án:** TRU_V1.0 — Trạm Sạc Điện  
**Ngày ban hành:** 31/03/2026  
**Người lập:** AI Assistant (theo yêu cầu Nguyễn Xuân Chiểu)  
**Tài liệu gốc:** `docs/MODBUS_REGISTER_MAP.md` (Rev 2.0)  
**Trạng thái:** 🔒 **ĐÓNG BĂNG** — Không sửa đổi tài liệu sau khi bàn giao

---

## 1. MỤC ĐÍCH

Yêu cầu bên **firmware STM32** cập nhật chương trình Modbus RTU Slave để bổ sung các **register, coil, error type** mới theo bảng Register Map phiên bản Rev 2.0. Mục tiêu:

- Hỗ trợ **Dynamic Load Balancing** (Gateway điều chỉnh dòng max từng trạm)
- Hỗ trợ **Session Management** (session_id, session_energy_limit, stop_reason)
- Hỗ trợ **Time Sync** từ Gateway (Unix timestamp qua Holding Register)
- Bổ sung cảm biến an toàn (**ground fault, connector status**)
- Chuẩn hóa **FSM State enum** đồng nhất giữa STM32 ↔ ESP32 ↔ Server
- Bổ sung **Alarm Flags mở rộng** (11 bit thay vì 8 bit)

---

## 2. CÁC HẠNG MỤC CẦN THỰC HIỆN

### 2.1. ✅ Xác nhận FSM State Enum (KHÔNG THAY ĐỔI CODE, chỉ xác nhận)

Kiểm tra firmware hiện tại đã tuân thủ đúng bảng enum dưới đây. **Đây là nguồn sự thật duy nhất** — Server MQTT sẽ decode theo đúng giá trị này.

| Giá trị | Tên State | Ghi chú |
|---------|-----------|---------|
| 0 | `INIT` | Khởi tạo hệ thống |
| 1 | `IDLE` | Sẵn sàng |
| 2 | `STANDBY` | Chờ cắm súng sạc |
| 3 | `CHARGING` | Đang cấp nguồn |
| 4 | `FINISH` | Hoàn tất phiên sạc |
| 5 | `ERROR` | Lỗi khẩn cấp |

> **Lưu ý:** Giá trị `255 (OFFLINE)` là do phía ESP32 Gateway tự gán khi mất kết nối Modbus — STM32 **KHÔNG** cần xử lý giá trị này.

---

### 2.2. 🆕 Thêm 7 Input Registers mới (FC04)

Các register cần bổ sung vào bảng phản hồi FC04, liên tiếp sau register `0x0025` hiện có:

| Addr | Tên | Kiểu | Đơn vị | Mô tả triển khai |
|------|------|------|--------|-------------------|
| **0x0026** | `frequency` | uint16 | 0.01Hz | Đọc từ đồng hồ DLT645 hoặc ADC zero-crossing. `50.00Hz → 5000`. Nếu chưa đo được thì trả `0xFFFF`. |
| **0x0027** | `power_factor` | uint16 | 0.001 | Hệ số công suất từ đồng hồ DLT645. `PF=0.95 → 950`. Nếu chưa đo được thì trả `0xFFFF`. |
| **0x0028** | `current_rms_raw` | uint16 | 0.001A | Dòng RMS gốc từ ADC (trước bộ lọc). Dùng để phát hiện **dòng dư khi IDLE** (relay dính). `0.100A → 100`. |
| **0x0029** | `session_id` | uint16 | - | **ID phiên sạc tự động tăng** khi FSM chuyển sang `CHARGING`. Bắt đầu từ 1, wrap tại 65535→1. Lưu Flash để không reset khi mất điện. |
| **0x002A** | `last_stop_reason` | uint16 | enum | Lý do dừng sạc gần nhất. Cập nhật khi chuyển `CHARGING→FINISH` hoặc `CHARGING→ERROR`. Xem bảng enum ở mục 2.7. |
| **0x002B** | `connector_status` | uint16 | enum | `0=Unplugged, 1=Plugged, 2=Locked`. Đọc từ GPIO cảm biến đầu cắm (nếu có). Nếu **chưa trang bị phần cứng**, trả `0xFFFF` (không xác định). |
| **0x002C** | `ground_fault` | uint16 | bool | `1=phát hiện rò điện ra vỏ`. Đọc từ mạch RCD/GFCI (nếu có). Nếu **chưa trang bị**, trả `0` (OK). |

> **QUAN TRỌNG:** Tổng FC04 tăng từ 38 registers lên **45 registers** (0x0000→0x002C). Master sẽ đọc `num_regs = 45` trong 1 request.

---

### 2.3. 🆕 Thêm 2 Discrete Inputs (FC02)

| Addr | Tên | Mô tả |
|------|------|--------|
| **0x0006** | `connector_plugged` | `1` = đầu sạc đã cắm. Mirror từ `connector_status ≥ 1`. |
| **0x0007** | `ground_fault_active` | `1` = rò dòng. Mirror từ `ground_fault == 1`. |

---

### 2.4. 🆕 Thêm 2 Coils (FC05)

| Addr | Tên | Hành vi khi nhận 0xFF00 |
|------|------|------------------------|
| **0x0005** | `force_fan_on` | Bật quạt **bắt buộc**, bỏ qua logic nhiệt độ. Tự tắt sau 5 phút hoặc khi nhận lại `0x0000`. Dùng khi kỹ thuật viên bảo trì. |
| **0x0006** | `enter_fw_update` | Đưa STM32 vào **chế độ Bootloader** (System Memory Boot). Lưu flag vào Flash, sau đó `NVIC_SystemReset()`. Bootloader sẵn sàng nhận firmware qua RS485 (tùy giao thức DFU). |

> **Lưu ý `enter_fw_update`:** Đây là tính năng **tùy chọn** (nice-to-have). Nếu chưa triển khai DFU qua RS485, có thể trả Modbus Exception Code 0x01 (Illegal Function) khi nhận Coil 0x0006.

---

### 2.5. 🆕 Thêm 4 Holding Registers (FC03/06/16)

| Addr | Tên | Default | Đơn vị | Mô tả triển khai |
|------|------|---------|--------|-------------------|
| **0x010A** | `current_limit` | 3200 | 0.01A | **Dynamic Load Balancing.** Gateway ghi giá trị này để giới hạn **dòng max** cho trạm (default 32.00A). STM32 phải: ① Lưu vào RAM ② So sánh `current` (0x0001) với `current_limit` mỗi chu kỳ ③ Nếu vượt > `current_limit + 10%` → trigger `ERR_OVERCURRENT`, cắt relay. |
| **0x010B** | `session_energy_limit` | 0 | Wh | **Giới hạn kWh mỗi phiên sạc.** `0 = disable`. Gateway ghi trước khi kích `start_charge` (Coil 0x0000). Khi `session_energy` (0x000C) ≥ giá trị này → tự dừng sạc, set `last_stop_reason = 5 (ENERGY_EXCEEDED)`. |
| **0x010C** | `time_sync_hi` | 0 | - | **Unix timestamp (high 16-bit).** Gateway ghi FC16 cặp 0x010C-0x010D mỗi 60s. STM32 dùng timestamp này cho Flash ErrLog. `uint32_t unix_ts = ((uint32_t)time_sync_hi << 16) | time_sync_lo`. |
| **0x010D** | `time_sync_lo` | 0 | - | **Unix timestamp (low 16-bit).** Luôn ghi cùng lúc với 0x010C qua FC16 (Write Multiple). |

> **Về current_limit:** Giá trị persist trong RAM (không cần lưu Flash). Nếu STM32 restart, Gateway sẽ ghi lại giá trị mới. Default 3200 (32A) là an toàn.

---

### 2.6. 🆕 Thêm 3 Error Types

Bổ sung vào bảng `error_type` cho register `0x0021` (`last_error_type`):

| ID | Tên | Logic kích hoạt trên STM32 |
|----|------|---------------------------|
| **8** | `ERR_GROUND_FAULT` | `ground_fault == 1`. Cắt relay ngay lập tức. Yêu cầu `clear_error` để reset. |
| **9** | `ERR_CONNECTOR_FAULT` | `connector_status` không hợp lệ (ví dụ: mất tín hiệu cảm biến giữa phiên sạc). |
| **10** | `ERR_OVERCURRENT` | `current > current_limit * 1.10`. Cắt relay. Set `alarm_flags` bit10. |

---

### 2.7. 🆕 Bảng Enum `last_stop_reason` (Register 0x002A)

| Giá trị | Tên | Khi nào set |
|---------|-----|-------------|
| 0 | `REASON_UNKNOWN` | Chưa có phiên sạc nào |
| 1 | `FINISHED_AUTO` | Dòng giảm dưới `min_current` → pin đầy |
| 2 | `REMOTE_STOP_USER` | Nhận Coil `stop_charge` (0x0001) từ Master |
| 3 | `REMOTE_STOP_OUT_OF_COIN` | Nhận `stop_charge` kèm `reason=3` (hết coin, do Server quyết định) |
| 4 | `SAFETY_ALARM_STOP` | ERR_OVERTEMP / ERR_VOLTAGE / ERR_GROUND_FAULT |
| **5** | **`SESSION_ENERGY_EXCEEDED`** | `session_energy ≥ session_energy_limit` (khi `session_energy_limit > 0`) |
| **6** | **`OVERCURRENT_STOP`** | Dòng vượt `current_limit + 10%` |

---

### 2.8. 🆕 Mở rộng `alarm_flags` (Register 0x0018)

Hiện tại 8 bit → **mở rộng thành 11 bit** (vẫn nằm trong 1 register uint16):

| Bit | Tên | Điều kiện |
|-----|------|-----------|
| 0 | OVERTEMP | NTC > `overtemp_limit` |
| 1 | DOOR | Cửa mở trái phép |
| 2 | TAMPER | Phá hoại |
| 3 | OVERPOWER | `power > max_power` |
| 4 | VOLTAGE | Ngoài 180-260V |
| 5 | ENERGY | Đạt `energy_limit` tổng |
| 6 | LOW_CURRENT | Dòng thấp bất thường khi sạc |
| 7 | COMM_FAIL | Mất DLT645 hoặc Master heartbeat timeout |
| **8** | **GROUND_FAULT** | Rò dòng ra vỏ |
| **9** | **CONNECTOR** | Đầu cắm bất thường |
| **10** | **OVERCURRENT** | Dòng vượt `current_limit` |

---

## 3. ĐỘ ƯU TIÊN TRIỂN KHAI

| Ưu tiên | Hạng mục | Lý do |
|---------|----------|-------|
| 🔴 **P0 — Bắt buộc** | FSM Enum xác nhận (2.1) | Server decode sai → tính sai tiền |
| 🔴 **P0 — Bắt buộc** | 7 Input Registers mới (2.2) | Gateway đọc 45 regs, thiếu sẽ CRC error |
| 🔴 **P0 — Bắt buộc** | `session_id` + `last_stop_reason` (2.2) | Liên kết phiên sạc START↔STOP |
| 🟠 **P1 — Nên có** | `current_limit` + `ERR_OVERCURRENT` (2.5, 2.6) | Dynamic Load Balancing |
| 🟠 **P1 — Nên có** | `session_energy_limit` (2.5) | Giới hạn kWh/phiên |
| 🟠 **P1 — Nên có** | `time_sync` (2.5) | Timestamp chuẩn cho ErrLog |
| 🟡 **P2 — Tùy chọn** | `connector_status` + `ground_fault` (2.2) | Tùy phần cứng (trả 0xFFFF nếu chưa có) |
| 🟡 **P2 — Tùy chọn** | `force_fan_on` coil (2.4) | Bảo trì |
| ⚪ **P3 — Tương lai** | `enter_fw_update` coil (2.4) | DFU qua RS485 (phức tạp) |

---

## 4. LƯU Ý KỸ THUẬT

### 4.1. Backward Compatibility
- Master (ESP32) sẽ đọc **45 registers** (FC04, 0x0000, num=45). Nếu STM32 firmware cũ chỉ có 38 registers, response sẽ trả **Modbus Exception Code 0x02** (Illegal Data Address).
- **Gợi ý:** Deploy firmware STM32 mới **TRƯỚC** khi deploy firmware ESP32 mới để tránh lỗi giao tiếp.

### 4.2. Register chưa có phần cứng
- `connector_status` (0x002B): Nếu chưa có cảm biến đầu cắm → trả `0xFFFF`.
- `ground_fault` (0x002C): Nếu chưa có mạch RCD → trả `0`.
- `frequency` (0x0026): Nếu đồng hồ DLT645 không đo frequency → trả `0xFFFF`.
- `power_factor` (0x0027): Tương tự → trả `0xFFFF`.
- Gateway sẽ hiểu `0xFFFF` = "không khả dụng" và bỏ qua field đó khi publish MQTT.

### 4.3. Flash Wear-out cho `session_id`
- `session_id` cần persist qua reset. Gợi ý: chỉ ghi Flash **khi bắt đầu phiên mới** (không ghi mỗi giây). Với 100,000 write cycles chia cho ~20 phiên/ngày = **~13 năm** tuổi thọ.

### 4.4. FC16 cho Time Sync
- Register 0x010C và 0x010D **phải được ghi cùng lúc** bằng FC16 (Write Multiple Registers) để đảm bảo tính nguyên tử. Không dùng FC06 ghi từng register riêng lẻ.

---

## 5. TEST CHECKLIST (cho bên STM32)

- [ ] FC04 đọc 45 registers (num_regs=45) trả về đúng 90 bytes data + CRC
- [ ] `session_id` tăng khi chuyển IDLE→STANDBY→CHARGING, persist qua reset
- [ ] `last_stop_reason` cập nhật đúng enum khi dừng sạc
- [ ] `alarm_flags` bit 8-10 hoạt động đúng
- [ ] Ghi FC06 vào `current_limit` (0x010A), kiểm tra relay cắt khi vượt ngưỡng
- [ ] Ghi FC06 vào `session_energy_limit` (0x010B), kiểm tra auto-stop khi đạt giới hạn
- [ ] Ghi FC16 vào `time_sync` (0x010C-0x010D), kiểm tra ErrLog có timestamp chuẩn
- [ ] Coil `force_fan_on` (0x0005) bật/tắt quạt đúng
- [ ] Registers chưa có phần cứng trả `0xFFFF` hoặc `0` mà **không crash**
- [ ] Master heartbeat (HR 0x0109) vẫn hoạt động đúng như cũ

---

## 6. TÀI LIỆU THAM CHIẾU

| File | Nội dung |
|------|----------|
| `docs/MODBUS_REGISTER_MAP.md` | **Bảng register đầy đủ** (nguồn sự thật duy nhất) |
| `docs/MQTT_PAYLOAD_V3.3.md` | Payload MQTT V3.4 — để hiểu data sẽ được dùng như thế nào trên Server |
| `docs/ESP32_STORE_AND_FORWARD.md` | Cơ chế lưu trữ offline — để hiểu vì sao cần `session_id` persist |
