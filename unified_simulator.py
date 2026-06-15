#!/usr/bin/env python3
import os
import time
import threading
import random
import logging
import json
import serial
import subprocess
from flask import Flask
from flask_socketio import SocketIO

# Pymodbus 3.x compatibility
try:
    from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext, ModbusSequentialDataBlock
except ImportError:
    from pymodbus.datastore import ModbusDeviceContext as ModbusSlaveContext, ModbusServerContext, ModbusSequentialDataBlock

from pymodbus.server import StartSerialServer
from pymodbus.framer import FramerRTU

# Enable Pymodbus Debug Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logging.getLogger("pymodbus").setLevel(logging.DEBUG)
logger = logging.getLogger("Simulator")

# ============================================================================
# Config
# ============================================================================
MODBUS_PORT = '/dev/ttyUSB0'
DLT645_PORT = '/dev/ttyUSB1'
SLAVE_IDS   = [2, 3, 4, 5, 6, 7]
DLT645_ADDR = [0x11, 0x22, 0x33, 0x44, 0x55, 0x66]
STATE_FILE  = "simulator_state.json"

STATE_INIT, STATE_IDLE, STATE_STANDBY, STATE_CHARGING, STATE_FINISH, STATE_ERROR = range(6)

stats = {
    "mb_pkts": 0, "dlt_pkts": 0,
    "mb_status": "Idle", "dlt_status": "Idle",
    "mb_rx_tick": 0, "dlt_rx_tick": 0
}

app = Flask(__name__, static_folder='web', static_url_path='')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ============================================================================
# Persistence
# ============================================================================
def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f: return json.load(f)
    except: pass
    return {"slaves": {}, "meter": {}}

def save_state(slaves, meter):
    state = {"slaves": {}, "meter": {}}
    for eid, emu in slaves.items():
        state["slaves"][str(eid)] = { "energy": emu.energy, "reboot_count": emu.reboot_count }
    state["meter"] = {"energy": meter.energy}
    try:
        with open(STATE_FILE, 'w') as f: json.dump(state, f, indent=2)
    except: pass

# ============================================================================
# Emulator Classes
# ============================================================================
class ChargerEmulator:
    def __init__(self, slave_id, initial_state):
        self.id = slave_id
        self.start_time = time.time()
        self.last_update = time.time()
        s = initial_state.get("slaves", {}).get(str(slave_id), {})
        self.energy = s.get("energy", 100.0 + slave_id * 5)
        self.reboot_count = s.get("reboot_count", 0) + 1
        self.sn_str = f"2026048899{slave_id:02d}"
        self.sn_bytes = [int(self.sn_str[i:i+2], 16) for i in range(0, 12, 2)]
        self.state = STATE_IDLE
        self.v, self.a, self.p, self.t = 220.0, 0.0, 0.0, 28.5
        self.sd, self.se = 0, 0
        self.charge_start_tick = 0
        self.plugged, self.door, self.fan = False, False, False
        self.hb = 0
        self.context = None

    def update(self):
        now = time.time()
        dt = now - self.last_update
        self.last_update = now
        self.hb = (self.hb + 1) & 0xFFFF
        self.v = 220.0 + random.uniform(-0.5, 0.5)
        if self.state == STATE_CHARGING:
            elapsed = now - self.charge_start_tick
            target_p = max(5.0, 1000.0 - (995.0 * min(1.0, elapsed/1800.0))) + random.uniform(-2, 2)
            self.p = target_p; self.a = self.p / self.v
            self.se += (self.p * dt) / 3600000.0; self.energy += (self.p * dt) / 3600000.0
            self.sd = int(elapsed); self.t = min(70.0, self.t + 0.05 * dt); self.fan = True
            if self.p < 10.0 and elapsed > 10: self.state = STATE_FINISH
        else:
            self.p, self.a = 0.0, 0.0; self.t = max(28.5, self.t - 0.02 * dt); self.fan = (self.t > 45.0)
        if self.context: self.sync_modbus()

    def sync_modbus(self):
        try:
            ir_vals = [0] * 300
            ir_vals[0x00], ir_vals[0x01], ir_vals[0x02] = int(self.v*10), int(self.a*100), int(self.p)
            ir_vals[0x03], ir_vals[0x04] = (int(self.energy*1000) >> 16) & 0xFFFF, int(self.energy*1000) & 0xFFFF
            ir_vals[0x05], ir_vals[0x06] = int(self.t), self.state
            ir_vals[0x07] = ( (1 if self.state == STATE_CHARGING else 0) << 2 | (1 if self.fan else 0) << 1 )
            ir_vals[0x0B], ir_vals[0x0C] = int(self.se * 1000), self.sd
            ir_vals[0x14] = self.hb
            ir_vals[0x15], ir_vals[0x16] = (int(time.time()-self.start_time) >> 16) & 0xFFFF, int(time.time()-self.start_time) & 0xFFFF
            ir_vals[0x17] = self.reboot_count
            ir_vals[0x18], ir_vals[0x19], ir_vals[0x1A] = (self.sn_bytes[0] | (self.sn_bytes[1]<<8)), (self.sn_bytes[2] | (self.sn_bytes[3]<<8)), (self.sn_bytes[4] | (self.sn_bytes[5]<<8))
            self.context.setValues(4, 0x00, ir_vals)
        except: pass

class MeterEmulator:
    def __init__(self, initial_state):
        s = initial_state.get("meter", {})
        self.energy = s.get("energy", 500.0)
        self.v, self.a, self.p, self.is_charging, self.start_tick, self.last_update = 220.0, 0.0, 0.0, False, 0, time.time()

    def update(self):
        now = time.time()
        dt = now - self.last_update
        self.last_update = now
        self.v = 220.0 + random.uniform(-0.5, 0.5)
        if self.is_charging:
            elapsed = now - self.start_tick
            tp = max(5.0, 1000.0 - (995.0 * min(1.0, elapsed/1800.0))) + random.uniform(-2, 2)
            self.p, self.a = tp / 1000.0, tp / self.v
            if tp < 10 and elapsed > 10: self.is_charging = False
        else: self.p, self.a = 0.015, 0.07
        self.energy += (self.p * dt) / 3600.0

    def get_bcd(self, di):
        if di == 0x02010100: return [(_ % 100 // 10 << 4 | _ % 10) + 0x33 for _ in [int(self.v*10) % 100, int(self.v*10)//100]]
        if di == 0x02020100: return [(_ % 100 // 10 << 4 | _ % 10) + 0x33 for _ in [int(self.a*1000)%100, (int(self.a*1000)//100)%100, (int(self.a*1000)//10000)%100]]
        if di == 0x02030000: return [(_ % 100 // 10 << 4 | _ % 10) + 0x33 for _ in [int(self.p*10000)%100, (int(self.p*10000)//100)%100, (int(self.p*10000)//10000)%100]]
        if di == 0x00010000:
            val = int(self.energy * 100)
            return [(_ % 100 // 10 << 4 | _ % 10) + 0x33 for _ in [val%100, (val//100)%100, (val//10000)%100, (val//1000000)%100]]
        return None

# ============================================================================
# Main
# ============================================================================
initial_state = load_state()
slaves = {i: ChargerEmulator(i, initial_state) for i in SLAVE_IDS}
meter = MeterEmulator(initial_state)

def modbus_thread():
    logger.info(f"Starting Modbus RTU Server on {MODBUS_PORT}...")
    try:
        slaves_context = {}
        for i in SLAVE_IDS:
            store = ModbusSlaveContext(
                di=ModbusSequentialDataBlock(0, [0]*300),
                co=ModbusSequentialDataBlock(0, [False]*300),
                hr=ModbusSequentialDataBlock(0, [0]*300),
                ir=ModbusSequentialDataBlock(0, [0]*300)
            )
            slaves_context[i] = store
            slaves[i].context = store
        context = ModbusServerContext(slaves=slaves_context, single=False)
        stats["mb_status"] = "Active"
        StartSerialServer(
            context=context, port=MODBUS_PORT, baudrate=9600, framer=FramerRTU,
            parity='N', stopbits=1, bytesize=8, timeout=0.001 # Aggressive timeout
        )
    except Exception as e:
        logger.error(f"Modbus Error: {e}")
        stats["mb_status"] = f"Error: {e}"

def dlt645_thread():
    logger.info(f"Starting DLT645 on {DLT645_PORT}...")
    try:
        ser = serial.Serial(DLT645_PORT, 2400, parity='E', timeout=0.05)
        stats["dlt_status"] = "Active"
    except Exception as e:
        stats["dlt_status"] = f"Error: {e}"; return
    buf = b''
    while True:
        try:
            if ser.in_waiting:
                buf += ser.read(ser.in_waiting)
                stats["dlt_rx_tick"] = time.time()
            while len(buf) > 0 and buf[0] != 0x68: buf = buf[1:]
            if len(buf) >= 12 and buf[0] == 0x68 and buf[7] == 0x68:
                ctrl, L = buf[8], buf[9]
                if len(buf) >= 10 + L + 2:
                    frame = buf[:10+L+2]; buf = buf[10+L+2:]
                    time.sleep(0.01)
                    if ctrl == 0x13:
                        r = [0x68] + DLT645_ADDR + [0x68, 0x93, 0x06] + DLT645_ADDR
                        ser.write(bytes([0xFE]*4 + r + [sum(r)%256, 0x16]))
                        stats["dlt_pkts"] += 1
                    elif ctrl == 0x11:
                        raw_di = [(frame[10+k]-0x33)&0xFF for k in range(4)]
                        di = raw_di[0] | (raw_di[1]<<8) | (raw_di[2]<<16) | (raw_di[3]<<24)
                        data = meter.get_bcd(di)
                        if data:
                            di_w = [((di >> (8*k)) & 0xFF) + 0x33 for k in range(4)]
                            r = [0x68] + DLT645_ADDR + [0x68, 0x91, len(data)+4] + di_w + data
                            ser.write(bytes([0xFE]*4 + r + [sum(r)%256, 0x16]))
                            stats["dlt_pkts"] += 1
            elif len(buf) > 100: buf = b''
        except: pass
        time.sleep(0.005)

def loop():
    while True:
        for s in slaves.values(): s.update()
        meter.update()
        socketio.emit('update', {
            "slaves": {id: {
                "v": round(s.v, 1), "a": round(s.a, 2), "p": round(s.p, 1), "e": round(s.energy, 3), "t": round(s.t, 1),
                "state": s.state, "sn": s.sn_str, "plug": s.plugged, "door": s.door, "hb": s.hb, "upt": int(time.time()-s.start_time), "rb": s.reboot_count, "sd": s.sd
            } for id, s in slaves.items()},
            "meter": {"v": round(meter.v, 1), "a": round(meter.a, 3), "p": round(meter.p*1000, 1), "e": round(meter.energy, 2), "charging": meter.is_charging},
            "sys": stats
        })
        save_state(slaves, meter)
        socketio.sleep(1)

@app.route('/')
def index(): return app.send_static_file('index.html')

@socketio.on('ui_command')
def handle_command(data):
    sid, act = int(data.get('id', -1)), data.get('action')
    if sid == 0:
        if act == 'start_charge': meter.is_charging = True; meter.start_tick = time.time()
        elif act == 'stop_charge': meter.is_charging = False
        elif act == 'restart_service': subprocess.Popen(["sudo", "systemctl", "restart", "charger-sim.service"])
    elif sid in slaves:
        s = slaves[sid]
        if act == 'start': s.state = STATE_CHARGING; s.charge_start_tick = time.time(); s.se = 0
        elif act == 'stop': s.state = STATE_IDLE
        elif act == 'toggle_plug': s.plugged = not s.plugged
        elif act == 'toggle_door': s.door = not s.door
        elif act == 'reset': s.state = STATE_IDLE; s.t = 28.5

if __name__ == "__main__":
    threading.Thread(target=modbus_thread, daemon=True).start()
    threading.Thread(target=dlt645_thread, daemon=True).start()
    socketio.start_background_task(loop)
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
