# 10-Slave Modbus RTU Simulator - Guide

Dự án này giả lập 10 trạm sạc (Slave ID 1-10) trên cùng một bus Serial (RS485) để phục vụ việc kiểm thử ESP32 Master.

## Cấu trúc thư mục
- `modbus_multi_slave.py`: Script chính (Backend).
- `web/`: Giao diện Dashboard (Frontend).
- `docs/`: Tài liệu tra cứu thanh ghi và hướng dẫn.

## Yêu cầu hệ thống
- Python 3.8+
- Thư viện: `pymodbus`, `pyserial`, `flask`, `flask-socketio`, `eventlet`

## Cách khởi động
1. Đảm bảo cổng `COM35` đã sẵn sàng (hoặc sửa đổi trong file `.py`).
2. Chạy lệnh:
   ```bash
   python modbus_multi_slave.py
   ```
3. Truy cập Dashboard tại: `http://localhost:5000`

## Tính năng Dashboard
- **Theo dõi thời gian thực**: Xem V, A, kW, kWh của từng Slave.
- **Điều khiển giả lập**:
  - `Start`: Giả lập bắt đầu sạc (FSM → CHARGING).
  - `Stop`: Giả lập kết thúc sạc (FSM → FINISH → IDLE).
  - `Fault`: Giả lập lỗi (FSM → ERROR) để test logic xử lý lỗi của Master.

## Bản đồ thanh ghi (Register Map)
Tham khảo file [MODBUS_REGISTER_MAP.md](docs/MODBUS_REGISTER_MAP.md) trong thư mục này để biết địa chỉ chi tiết.
- **Input Registers (0x0000 - 0x002C)**: 45 thanh ghi dữ liệu.
- **Coils (0x0000 - 0x0006)**: Các lệnh điều khiển từ Master.
- **Holding Registers (0x0100 - 0x010D)**: Các tham số cấu hình.
