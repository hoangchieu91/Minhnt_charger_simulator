# ADDENDUM 01: Sửa Lỗi Xung Đột Chân UART (BUG-2 & BUG-8)

**Ngày cập nhật:** 05/04/2026
**Tham chiếu lỗi:** BUG-2 (Conflict UART0) và BUG-8 (com1_enable bị tắt).

## 1. Mô tả sự cố
Trong quá trình rà soát Firmware gốc của Gateway ESP32, phát hiện cấu hình chân UART cho giao tiếp RS485 (COM1) trong `board_hal.h` đang được trỏ vào:
- `PIN_RS485_1_TX`: **GPIO_NUM_1**
- `PIN_RS485_1_RX`: **GPIO_NUM_3**

Đây là hai chân mặc định dành cho **UART0 (USB Serial Console)**. Việc dùng chung gây ra sự cố crash / mất debug khi Modbus RS485 kích hoạt. Để tạm né tránh điều kiện này, lập trình viên trước đã vô hiệu hóa biến cấu hình `g_config.com1_enable = false;` (BUG-8) trong file `app_main.c`, khiến Firmware chạy thực tế chỉ là vỏ bọc không giao tiếp được với Slaves.

## 2. Phương án khắc phục
Sau khi xác nhận lại với Schematic phần cứng thực tế, các chân RS485_1 (COM1) đã bị hàn/thiết kế cứng vào GPIO_1 & GPIO_3. Chân GPIO_17/16 thực chất không được đấu nối đến IC RS485_1.

Do đó, bắt buộc phải:
- Vô hiệu hóa phân hệ COM1 (RS485_1) trên Firmware để nhường GPIO1/3 bảo toàn luồng Serial Console (Dùng chẩn đoán lỗi).
- Chuyển toàn bộ tải Master sang **COM2 (RS485_2)** - Cấu hình trên hệ GPIO dự phòng (`IO32 / IO33`).

Trong `firmware/main/app_main.c` đã cấu hình lại:
  - Đặt `g_config.com1_enable = false;` (Tắt COM1)
  - Đặt `g_config.com2_enable = true;` (Bật COM2 với baudrate 9600)
  - Đặt `g_config.com2_slave_count = 10;` (cho mục đích giao tiếp).

## 3. Kết luận
Ở phiên bản Dev này, tủ sạc sẽ sử dụng ngõ ngoại vi COM2 thay vì COM1. Firmware giờ đây có thể flash và nạp an toàn, hệ thống hoạt động ổn định và giữ nguyên khả năng Serial Monitor. Đoàn đội phát triển có thể nối dây RS485 vật lý sang chân RS485_2 trên bo mạch để giao tiếp STM32.
