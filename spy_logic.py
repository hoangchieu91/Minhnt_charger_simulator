import socketio
import time

sio = socketio.Client()

@sio.on('update')
def on_update(data):
    if '1' in data:
        tel = data['1']
        v = tel['v']
        meter_valid = tel['raw_ir'][26]
        print(f"Voltage: {v} | MeterValid: {meter_valid}")

def run_spy():
    try:
        sio.connect('http://localhost:5000')
        print("Spy connected. Waiting for 2s...")
        time.sleep(2)
        
        # Trigger Meter Offline via Socket.IO
        print("Toggling Meter for station 1...")
        sio.emit('ui_command', {'id': 1, 'action': 'toggle_meter'})
        
        # Watch for 5 updates
        time.sleep(5)
        sio.disconnect()
    except Exception as e:
        print(f"Spy Error: {e}")

if __name__ == "__main__":
    run_spy()
