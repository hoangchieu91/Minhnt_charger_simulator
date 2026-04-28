import serial
import time

def sniff(port):
    print(f"Sniffing {port}...")
    try:
        ser = serial.Serial(port, 2400, parity='E', timeout=1)
        while True:
            data = ser.read(100)
            if data:
                print(f"{port}: {data.hex().upper()}")
    except Exception as e:
        print(f"{port} Error: {e}")

if __name__ == "__main__":
    import threading
    threading.Thread(target=sniff, args=('/dev/ttyUSB0',), daemon=True).start()
    threading.Thread(target=sniff, args=('/dev/ttyUSB1',), daemon=True).start()
    time.sleep(10)
