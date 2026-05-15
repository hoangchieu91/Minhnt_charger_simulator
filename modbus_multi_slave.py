import os
import time
import threading
import random
import logging
import math
import json
from flask import Flask
from flask_socketio import SocketIO, emit

# Pymodbus 2.5.x compatible imports
from pymodbus.server.sync import StartSerialServer
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock
from pymodbus.transaction import ModbusRtuFramer

# ============================================================================
# Flask & SocketIO
# ============================================================================
app = Flask(__name__, static_folder='web', static_url_path='')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', manage_session=False)

logging.basicConfig(level=logging.WARNING)
logging.getLogger("pymodbus").setLevel(logging.ERROR)

# ============================================================================
# Config
# ============================================================================
SLAVE_IDS  = [2, 3, 4, 5, 6, 7]
PORT       = '/dev/ttyUSB0'
BAUDRATE   = 115200
STATE_FILE = "simulator_state.json"

# FSM States
STATE_INIT     = 0
STATE_IDLE     = 1
STATE_STANDBY  = 2
STATE_CHARGING = 3
STATE_FINISH   = 4
STATE_ERROR    = 5

# Stop reasons
STOP_UNKNOWN         = 0
STOP_FINISHED_AUTO   = 1
STOP_REMOTE_USER     = 2
STOP_OUT_OF_COIN     = 3
STOP_SAFETY_ALARM    = 4
STOP_ENERGY_EXCEEDED = 5
STOP_OVERCURRENT     = 6

# ============================================================================
# Persistence
# ============================================================================
def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f: return json.load(f)
    except: pass
    return {"slaves": {}}

def save_state(emulators):
    state = {"slaves": {}}
    for eid, emu in emulators.items():
        state["slaves"][str(eid)] = {
            "energy": emu.energy, "boot_count": emu.boot_count,
            "total_charge_count": emu.total_charge_count,
            "session_id": emu.session_id, "sn_str": emu.sn_str
        }
    try:
        with open(STATE_FILE, 'w') as f: json.dump(state, f, indent=2)
    except: pass

# ============================================================================
# ChargerEmulator — Rev 4.0.4 (Aligned with firmware)
# ============================================================================
class ChargerEmulator:
    def __init__(self, slave_id):
        self.id   = slave_id
        self.state = STATE_IDLE
        self.last_update = time.time()

        global global_state
        s = global_state.get("slaves", {}).get(str(slave_id), {})
        self.energy              = s.get("energy", random.randint(100000, 200000))
        self.boot_count          = s.get("boot_count", 0) + 1
        self.total_charge_count  = s.get("total_charge_count", 0)
        self.session_id          = s.get("session_id", 1000)
        self.sn_str              = s.get("sn_str", "".join([str(random.randint(0,9)) for _ in range(12)]))

        def sn_word(s4):
            b0 = int(s4[0])*16 + int(s4[1])
            b1 = int(s4[2])*16 + int(s4[3])
            return b0 | (b1 << 8)
        self.sn_w1 = sn_word(self.sn_str[0:4])
        self.sn_w2 = sn_word(self.sn_str[4:8])
        self.sn_w3 = sn_word(self.sn_str[8:12])

        self.door_open = False
        self.relays    = {"CHARGER": False, "FAN": False, "DOORLOCK": False, "SOCKET": False}
        self.ntc_temp    = 285
        self.voltage_base = 2200
        self.voltage     = 2200
        self.current     = 0
        self.power       = 0
        self.frequency   = 5000
        self.power_factor = 1000
        self.plugged     = False
        self.ground_fault = False
        self.lock_active = False
        self.lock_start_time = 0
        self.fan_forced = False
        self.fan_forced_time = 0

        self.session_energy   = 0
        self.start_energy     = int(self.energy)
        self.session_duration = 0
        self.stop_reason      = STOP_UNKNOWN

        self.fan_hi_temp    = 450
        self.fan_lo_temp    = 380
        self.overtemp_limit = 750
        self.max_power      = 1200
        self.low_p_thresh   = 50
        self.low_p_time     = 300
        self.energy_limit   = 0
        self.current_limit  = 1000
        self.door_logic     = 0

        self.alarm_flags      = 0
        self.master_alive     = 0
        self.uptime           = 0.0
        self.heartbeat_ctr    = 0
        self.meter_online     = True

        self.last_hb_time = time.time()
        self.last_hb_val  = 0
        self.context      = None

    def update(self):
        now = time.time()
        dt  = now - self.last_update
        self.last_update = now
        self.uptime += dt
        self.heartbeat_ctr = int(self.uptime) & 0xFFFF

        if self.master_alive == 1 and (now - self.last_hb_time) > 180.0:
            self.master_alive = 2
            self.trigger_error(7)

        self.voltage = int(self.voltage_base + random.gauss(0, 3))
        self.frequency = int(max(4950, min(5050, 5000 + random.gauss(0, 5))))

        if self.state == STATE_CHARGING:
            self.session_duration += dt
            p_kw = (self.max_power / 1000.0)
            self.current = int(p_kw * 1000 / max(self.voltage / 10.0, 1.0) * 100)
            self.current = min(self.current, self.current_limit)
            self.power   = int((self.voltage / 10.0) * (self.current / 100.0))
            added_wh = (self.power * dt) / 3600.0
            self.session_energy += added_wh
            self.energy         += added_wh
            self.relays["CHARGER"] = True
        else:
            self.current = 0; self.power = 0
            self.relays["CHARGER"] = False

        if self.lock_active and (now - self.lock_start_time) >= 5:
            self.lock_active = False; self.relays["DOORLOCK"] = False

        if self.context: self.sync_context()

    def sync_context(self):
        ir = [0] * 64
        relay_bits = (0x01 if self.relays["CHARGER"]  else 0) | \
                     (0x02 if self.relays["FAN"]      else 0) | \
                     (0x04 if self.relays["DOORLOCK"] else 0) | \
                     (0x08 if self.relays["SOCKET"]   else 0)

        status_bits = (0x01 if self.door_open else 0) | (0x02 if self.fan_forced else 0)

        total_e = int(self.energy)
        ir[0x00] = self.voltage
        ir[0x01] = self.current
        ir[0x02] = self.power
        ir[0x03] = (total_e >> 16) & 0xFFFF
        ir[0x04] = total_e & 0xFFFF
        ir[0x05] = int(self.ntc_temp)
        ir[0x06] = self.state
        ir[0x07] = relay_bits
        ir[0x08] = self.alarm_flags
        ir[0x09] = (int(self.start_energy) >> 16) & 0xFFFF
        ir[0x0A] = int(self.start_energy) & 0xFFFF
        ir[0x0B] = int(self.session_energy)
        ir[0x0C] = int(self.session_duration)
        ir[0x0D] = (self.session_id >> 16) & 0xFFFF
        ir[0x0E] = self.session_id & 0xFFFF
        ir[0x0F] = self.stop_reason
        ir[0x10] = 1 if self.meter_online else 0
        ir[0x11] = self.frequency
        ir[0x12] = self.power_factor
        ir[0x13] = status_bits
        ir[0x14] = self.heartbeat_ctr
        ir[0x15] = (int(self.uptime) >> 16) & 0xFFFF
        ir[0x16] = int(self.uptime) & 0xFFFF
        ir[0x17] = self.boot_count & 0xFFFF
        ir[0x18] = self.sn_w1
        ir[0x19] = self.sn_w2
        ir[0x1A] = self.sn_w3
        self.context.setValues(4, 0x0000, ir)

        di = [0] * 8
        di[0] = 1 if self.door_open else 0
        di[1] = 1 if self.state == STATE_CHARGING else 0
        di[2] = 1 if self.state == STATE_ERROR else 0
        di[3] = 1 if self.relays["FAN"] else 0
        di[4] = 1 if self.lock_active else 0
        di[6] = 1 if self.plugged else 0
        self.context.setValues(2, 0x0000, di)

        coils = self.context.getValues(1, 0x0000, count=8)
        if coils[0]:   self.start_charge()
        elif coils[1]: self.stop_charge(); self.stop_reason = STOP_REMOTE_USER
        elif coils[2]: self.unlock_door()
        elif coils[3]: self.clear_error()
        elif coils[4]: self.state = STATE_STANDBY
        elif coils[5]: self.fan_forced = True; self.fan_forced_time = time.time()
        elif coils[7]: self.relays["SOCKET"] = True
        if any(coils): self.context.setValues(1, 0x0000, [0]*8)

        hr = self.context.getValues(3, 0x0100, count=16)
        if hr[9] != self.last_hb_val:
            self.last_hb_val  = hr[9]
            self.last_hb_time = time.time()
            self.master_alive = 1
        self.current_limit = hr[7] or 1000
        self.energy_limit  = hr[6]

    def start_charge(self):
        if self.state != STATE_ERROR:
            self.state = STATE_CHARGING
            self.session_id = (self.session_id + 1) & 0xFFFFFFFF
            self.session_energy = 0; self.start_energy = int(self.energy)

    def stop_charge(self):
        if self.state == STATE_CHARGING: self.state = STATE_FINISH

    def unlock_door(self):
        self.relays["DOORLOCK"] = True; self.lock_active = True; self.lock_start_time = time.time()

    def trigger_error(self, bit):
        self.state = STATE_ERROR; self.alarm_flags |= (1 << bit)

    def clear_error(self):
        self.state = STATE_IDLE; self.alarm_flags = 0; self.last_hb_time = time.time()

global_state = load_state()
emulators = {i: ChargerEmulator(i) for i in SLAVE_IDS}

@app.route('/')
def index(): return "Minhnt Charger Multi-Slave Simulator Aligned with v4.0.4"

def background_task():
    while True:
        for emu in emulators.values(): emu.update()
        socketio.sleep(1)

def run_server():
    def start_modbus():
        try:
            slaves = {}
            for i in SLAVE_IDS:
                slaves[i] = ModbusSlaveContext(
                    di=ModbusSequentialDataBlock(0, [0]*100),
                    co=ModbusSequentialDataBlock(0, [0]*100),
                    ir=ModbusSequentialDataBlock(0, [0]*100),
                    hr=ModbusSequentialDataBlock(0, [0]*512),
                    zero_mode=True
                )
                emulators[i].context = slaves[i]
                slaves[i].setValues(3, 0x0100, [450, 380, 750, 1200, 50, 300, 0, 1000, 0, 0])
            server_context = ModbusServerContext(slaves=slaves, single=False)
            StartSerialServer(context=server_context, framer=ModbusRtuFramer, port=PORT, baudrate=BAUDRATE, timeout=0.05)
        except Exception as e:
            print(f"Modbus Error: {e}")

    socketio.start_background_task(background_task)
    threading.Thread(target=start_modbus, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=5001, debug=False, allow_unsafe_werkzeug=True)

if __name__ == "__main__": run_server()
