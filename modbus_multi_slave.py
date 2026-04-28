import os
import time
import threading
import random
import logging
import math
import json
from flask import Flask
from flask_socketio import SocketIO, emit

from pymodbus.server import StartSerialServer
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock
from pymodbus.framer import ModbusRtuFramer

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
PORT       = 'COM37'
BAUDRATE   = 9600
STATE_FILE = "simulator_state.json"

# FSM States (nguồn sự thật duy nhất — khớp firmware)
STATE_INIT     = 0
STATE_IDLE     = 1
STATE_STANDBY  = 2
STATE_CHARGING = 3
STATE_FINISH   = 4
STATE_ERROR    = 5

# Stop reasons (HR 0x000F)
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
# ChargerEmulator — Rev 2.0 (khớp modbus_slave.c)
# ============================================================================
class ChargerEmulator:
    def __init__(self, slave_id):
        self.id   = slave_id
        self.state = STATE_IDLE
        self.last_update = time.time()

        # --- Persistence ---
        global global_state
        s = global_state.get("slaves", {}).get(str(slave_id), {})
        self.energy              = s.get("energy", random.randint(100000, 200000))
        self.boot_count          = s.get("boot_count", 0) + 1
        self.total_charge_count  = s.get("total_charge_count", 0)
        self.session_id          = s.get("session_id", 1000)  # 32-bit, persist
        self.sn_str              = s.get("sn_str", "".join([str(random.randint(0,9)) for _ in range(12)]))

        # SN → 3 Modbus words (BCD pairs, little-endian within word)
        def sn_word(s4):
            b0 = int(s4[0])*16 + int(s4[1])
            b1 = int(s4[2])*16 + int(s4[3])
            return b0 | (b1 << 8)
        self.sn_w1 = sn_word(self.sn_str[0:4])
        self.sn_w2 = sn_word(self.sn_str[4:8])
        self.sn_w3 = sn_word(self.sn_str[8:12])

        # --- Hardware ---
        self.door_open = False
        self.relays    = {"CHARGER": False, "FAN": False, "DOORLOCK": False}
        self.leds      = {"RED": False, "GREEN": False, "WHITE": True}
        self.lock_active     = False
        self.lock_start_time = 0
        self.fan_forced      = False
        self.fan_forced_time = 0

        # --- Physics ---
        self.ntc_temp    = 285        # 0.1°C
        self.voltage_base = 2200
        self.voltage     = 2200
        self.current     = 0
        self.power       = 0
        self.frequency   = 5000       # 0.01 Hz → 50.00 Hz
        self.power_factor = 1000      # 0.001 → 1.000
        self.plugged     = False
        self.ground_fault       = False
        self.connector_status   = 0xFFFF  # N/A (no HW sensor)

        # --- Session ---
        self.session_energy   = 0
        self.start_energy     = int(self.energy)
        self.session_duration = 0
        self.stop_reason      = STOP_UNKNOWN

        # --- Holding Registers (HR 0x0100-0x010E, mặc định theo spec) ---
        self.fan_hi_temp    = 450     # HR 0x0100
        self.fan_lo_temp    = 380     # HR 0x0101
        self.overtemp_limit = 750     # HR 0x0102 (75.0°C)
        self.max_power      = 1200    # HR 0x0103 (W)
        self.low_p_thresh   = 50      # HR 0x0104 (W — pin đầy)
        self.low_p_time     = 300     # HR 0x0105 (s)
        self.energy_limit   = 0       # HR 0x0106 (Wh/session, 0=disable)
        self.current_limit  = 1000    # HR 0x0107 (0.01A = 10.00A)
        self.door_logic     = 0       # HR 0x0108

        # --- Diagnostics ---
        self.alarm_flags      = 0
        self.master_alive     = 0     # 0=no HB yet, 1=alive, 2=timeout
        self.uptime           = 0.0
        self.heartbeat_ctr    = 0
        self.meter_online     = True

        # --- Timers ---
        self.fan_on_time          = 0
        self.low_curr_start_time  = 0
        self.last_hb_time         = time.time()
        self.last_hb_val          = 0
        self.last_hb_str          = "--:--:--"
        self.last_log_time        = 0

        # --- Sim modes ---
        self.jitter_mode    = False
        self.leakage_sim    = False
        self.master_fail_sim = False
        self.manual_override = False

        self.context      = None
        self.raw_ir_cache = [0] * 60

    # ── Physics Update ──────────────────────────────────────────────────────
    def update(self):
        now = time.time()
        dt  = now - self.last_update
        self.last_update = now
        self.uptime += dt
        self.heartbeat_ctr = int(self.uptime) & 0xFFFF

        # Master heartbeat watchdog (180s per firmware)
        if not self.master_fail_sim:
            if self.master_alive == 1 and (now - self.last_hb_time) > 180.0:
                self.master_alive = 2
                self.trigger_error(7)  # COMM_FAIL
        else:
            self.master_alive = 2

        # Voltage
        v_noise = random.gauss(0, 3) if self.jitter_mode else 0
        self.voltage = int(self.voltage_base + v_noise)

        # Frequency (50 Hz ± noise)
        f_noise = random.gauss(0, 2) if self.jitter_mode else random.gauss(0, 0.3)
        self.frequency = int(max(4950, min(5050, 5000 + f_noise)))

        # Temperature & fan hysteresis
        if not self.manual_override:
            if self.state == STATE_CHARGING: self.ntc_temp += 0.8 * dt
            else: self.ntc_temp = max(285, self.ntc_temp - 0.4 * dt)

        if self.ntc_temp >= self.fan_hi_temp and not self.relays["FAN"]:
            self.relays["FAN"] = True; self.fan_on_time = now
        elif self.ntc_temp <= self.fan_lo_temp and self.relays["FAN"] and not self.fan_forced:
            if (now - self.fan_on_time) >= 30: self.relays["FAN"] = False

        if self.fan_forced:
            self.relays["FAN"] = True
            if (now - self.fan_forced_time) >= 300: self.fan_forced = False

        if self.ntc_temp > self.overtemp_limit:
            self.trigger_error(0)  # OVERTEMP

        # Charging physics
        if self.state == STATE_CHARGING:
            self.session_duration += dt
            t_phut = (self.session_duration * 6) / 60.0
            p_kw = (self.max_power / 1000.0) * (1.0 if t_phut <= 10 else math.exp(-0.05*(t_phut-10)))

            base_i = int(p_kw * 1000 / max(self.voltage / 10.0, 1.0) * 100)
            allowed = min(base_i, self.current_limit)
            a_noise = random.gauss(0, 5) if self.jitter_mode else 0
            self.current = int(max(allowed + a_noise, 0))
            self.power   = int((self.voltage / 10.0) * (self.current / 100.0))

            pf_noise = random.gauss(0, 5) if self.jitter_mode else 0
            self.power_factor = int(max(900, min(1000, 975 + pf_noise)))

            added_wh = (self.power * dt) / 3600.0
            self.session_energy += added_wh
            self.energy         += added_wh

            # Overcurrent: > limit + 10%
            if self.current > self.current_limit * 1.10:
                self.alarm_flags |= (1 << 10)
                self.stop_reason = STOP_OVERCURRENT
                self.trigger_error(10)

            # Session energy limit (HR 0x0106)
            if self.energy_limit > 0 and int(self.session_energy) >= self.energy_limit:
                self.stop_reason = STOP_ENERGY_EXCEEDED
                self.stop_charge()

            # Auto-finish: low current 60s
            if self.current < 50:
                if self.low_curr_start_time == 0: self.low_curr_start_time = now
                elif (now - self.low_curr_start_time) >= 60:
                    self.stop_reason = STOP_FINISHED_AUTO
                    self.stop_charge()
            else:
                self.low_curr_start_time = 0
        else:
            if self.leakage_sim:
                self.current = 150; self.power = int((self.voltage/10.0)*1.5)
                self.alarm_flags |= (1 << 8)
            else:
                self.current = 0; self.power = 0
                self.alarm_flags &= ~(1 << 8)
            self.power_factor = 1000

        # Tamper
        if self.door_open and not self.lock_active:
            self.trigger_error(2)  # TAMPER

        # Door lock auto-relock (5s)
        if self.lock_active and (now - self.lock_start_time) >= 5:
            self.lock_active = False; self.relays["DOORLOCK"] = False

        self._update_leds(now)
        if self.context: self.sync_context()

    def _update_leds(self, now):
        blink = (int(now * 2) % 2) == 0
        if self.state == STATE_IDLE:     self.leds = {"RED": False, "GREEN": False, "WHITE": True}
        elif self.state == STATE_STANDBY: self.leds = {"RED": False, "GREEN": blink, "WHITE": False}
        elif self.state == STATE_CHARGING:self.leds = {"RED": blink, "GREEN": False, "WHITE": False}
        elif self.state == STATE_FINISH:  self.leds = {"RED": False, "GREEN": True,  "WHITE": False}
        elif self.state == STATE_ERROR:   self.leds = {"RED": True,  "GREEN": False, "WHITE": False}
        if self.state == STATE_ERROR:
            self.relays["CHARGER"] = False

    # ── Modbus Context Sync (khớp modbus_slave.c read_input_register()) ─────
    def sync_context(self):
        # ── FC04 Input Registers ──────────────────────────────────────────
        # Layout PHẢI khớp chính xác với modbus_slave.c read_input_register()
        ir = [0] * 60

        relay_bits = (0x01 if self.relays["CHARGER"]  else 0) | \
                     (0x04 if self.relays["FAN"]       else 0) | \
                     (0x08 if self.relays["DOORLOCK"]  else 0)

        status_bits = (0x01 if self.door_open   else 0) | \
                      (0x02 if self.fan_forced   else 0)

        total_e = int(self.energy)

        ir[0x00] = self.voltage
        ir[0x01] = self.current
        ir[0x02] = self.power
        ir[0x03] = (total_e >> 16) & 0xFFFF          # energy_hi
        ir[0x04] = total_e & 0xFFFF                   # energy_lo
        ir[0x05] = int(self.ntc_temp)
        ir[0x06] = self.state
        ir[0x07] = relay_bits
        ir[0x08] = self.alarm_flags                   # ← dời từ 0x18 cũ!
        ir[0x09] = (int(self.start_energy) >> 16) & 0xFFFF  # start_e_hi (MỚI)
        ir[0x0A] = int(self.start_energy) & 0xFFFF          # start_e_lo (MỚI)
        ir[0x0B] = int(self.session_energy)           # session_energy (MỚI pos)
        ir[0x0C] = int(self.session_duration)         # duration       (MỚI pos)
        ir[0x0D] = (self.session_id >> 16) & 0xFFFF  # session_id_hi 32-bit (MỚI)
        ir[0x0E] = self.session_id & 0xFFFF           # session_id_lo (MỚI)
        ir[0x0F] = self.stop_reason                   # last_stop_reason (MỚI)
        ir[0x10] = 1 if self.meter_online else 0      # meter_valid    (MỚI pos)
        ir[0x11] = self.frequency                     # frequency 0.01Hz (MỚI)
        ir[0x12] = self.power_factor                  # power_factor 0.001 (MỚI)
        ir[0x13] = status_bits                        # status_bits (MỚI)
        ir[0x14] = self.heartbeat_ctr                 # heartbeat      (MỚI pos)
        ir[0x15] = (int(self.uptime) >> 16) & 0xFFFF # uptime_hi      (MỚI pos)
        ir[0x16] = int(self.uptime) & 0xFFFF          # uptime_lo
        ir[0x17] = self.boot_count & 0xFFFF           # reboot_count   (MỚI pos)
        ir[0x18] = self.sn_w1                         # meter_serial_1 (MỚI pos)
        ir[0x19] = self.sn_w2                         # meter_serial_2
        ir[0x1A] = self.sn_w3                         # meter_serial_3

        # Debug registers (0x30–0x33)
        ir[0x30] = 0   # error_count (placeholder)
        ir[0x31] = self.total_charge_count & 0xFFFF
        ir[0x32] = 0   # dlt645_ok
        ir[0x33] = 0   # dlt645_fail

        self.raw_ir_cache = list(ir)
        self.context.setValues(4, 0x0000, ir)

        # Modbus log
        if (time.time() - self.last_log_time) > 0.5:
            self.last_log_time = time.time()
            socketio.emit('modbus_log', f"[RX] Slave:{self.id:02d} FC04 Addr:0000 Len:22")

        # ── FC02 Discrete Inputs ──────────────────────────────────────────
        tamper = self.door_open and not self.lock_active
        di = [0] * 8
        di[0] = 1 if self.door_open                   else 0  # door_open
        di[1] = 1 if self.state == STATE_CHARGING      else 0  # is_charging
        di[2] = 1 if self.state == STATE_ERROR         else 0  # is_error
        di[3] = 1 if self.relays["FAN"]               else 0  # fan_running
        di[4] = 1 if self.lock_active                  else 0  # door_unlocked (MỚI)
        di[5] = 1 if tamper                            else 0  # tamper (MỚI)
        di[6] = 1 if (self.plugged or self.connector_status == 1) else 0  # connector_plugged (MỚI)
        di[7] = 1 if self.ground_fault                else 0  # ground_fault_active (MỚI)
        self.context.setValues(2, 0x0000, di)

        # ── FC01 Coils (read-back, always 0 — self-reset) ────────────────
        coils = self.context.getValues(1, 0x0000, count=7)
        if coils[0]:   self.start_charge()
        elif coils[1]: self.stop_charge(); self.stop_reason = STOP_REMOTE_USER
        elif coils[2]: self.unlock_door()
        elif coils[3]: self.clear_error()
        elif coils[4]: self.state = STATE_STANDBY
        elif coils[5]: self.fan_forced = True; self.fan_forced_time = time.time()  # force_fan_on (MỚI)
        if any(coils[:7]): self.context.setValues(1, 0x0000, [0]*7)

        # ── FC03 Holding Registers (read config from Master) ─────────────
        # HR 0x0109 — Master Heartbeat
        hr_hb = self.context.getValues(3, 0x0109, count=1)
        if hr_hb[0] != self.last_hb_val:
            self.last_hb_val  = hr_hb[0]
            self.last_hb_time = time.time()
            self.last_hb_str  = time.strftime('%H:%M:%S')
            if not self.master_fail_sim: self.master_alive = 1
            socketio.emit('modbus_log', f"[RX] Slave:{self.id:02d} HB={hr_hb[0]}")

        # HR 0x0107 — current_limit (Dynamic Load Balancing)
        self.current_limit = self.context.getValues(3, 0x0107, count=1)[0] or 1000

        # HR 0x0106 — session energy limit
        self.energy_limit = self.context.getValues(3, 0x0106, count=1)[0]

        # HR 0x010D-0x010E — time_sync (just store, no RTC in sim)
        # (no action needed in simulator)

    # ── FSM Actions ─────────────────────────────────────────────────────────
    def start_charge(self):
        if self.state not in (STATE_ERROR,):
            self.plugged          = True
            self.state            = STATE_CHARGING
            self.relays["CHARGER"] = True
            self.session_id       = (self.session_id + 1) & 0xFFFFFFFF
            self.session_energy   = 0
            self.session_duration = 0
            self.start_energy     = int(self.energy)
            self.stop_reason      = STOP_UNKNOWN
            self.low_curr_start_time = 0

    def stop_charge(self):
        if self.state in (STATE_CHARGING, STATE_STANDBY):
            self.state = STATE_FINISH
            self.relays["CHARGER"] = False
            self.total_charge_count += 1

    def unlock_door(self):
        self.relays["DOORLOCK"] = True
        self.lock_active     = True
        self.lock_start_time = time.time()

    def trigger_error(self, bit):
        self.state = STATE_ERROR
        self.alarm_flags |= (1 << bit)
        self.stop_reason = STOP_SAFETY_ALARM

    def clear_error(self):
        if not self.door_open and self.ntc_temp < self.overtemp_limit:
            self.state       = STATE_IDLE
            self.alarm_flags = 0
            self.last_hb_time = time.time()


# ============================================================================
# Web Dashboard (giữ nguyên)
# ============================================================================
global_state = load_state()
emulators = {i: ChargerEmulator(i) for i in SLAVE_IDS}

@app.route('/')
def index(): return app.send_static_file('index.html')

@socketio.on('ui_command')
def handle_ui_command(data):
    sid = int(data.get('id')); act = data.get('action'); val = data.get('value')
    if sid not in emulators: return
    emu = emulators[sid]
    if   act == 'set_temp':      emu.ntc_temp = int(float(val)*10); emu.manual_override = True
    elif act == 'set_current':   emu.current_limit = int(float(val)*100)
    elif act == 'door':          emu.door_open = not emu.door_open
    elif act == 'toggle_jitter': emu.jitter_mode = not emu.jitter_mode
    elif act == 'toggle_meter':  emu.meter_online = not emu.meter_online
    elif act == 'toggle_plug':   emu.plugged = not emu.plugged
    elif act == 'jitter':        emu.jitter_mode = not emu.jitter_mode
    elif act == 'master_fail':   emu.master_fail_sim = not emu.master_fail_sim
    elif act == 'reset':         emu.clear_error()
    elif act == 'unlock':        emu.unlock_door()
    elif act == 'start':         emu.start_charge()
    elif act == 'stop':          emu.stop_charge(); emu.stop_reason = STOP_REMOTE_USER

def background_task():
    save_counter = 0
    while True:
        data = {}
        for eid, emu in emulators.items():
            emu.update()
            data[eid] = {
                'state': emu.state,
                'v': round(emu.voltage/10.0, 1),
                'a': round(emu.current/100.0, 2),
                'p': emu.power,
                'se': round(emu.session_energy, 1),
                't': round(emu.ntc_temp/10.0, 1),
                'tot_e': emu.energy,
                'freq': round(emu.frequency/100.0, 2),
                'pf': round(emu.power_factor/1000.0, 3),
                'sn': emu.sn_str,
                'hb_time': emu.last_hb_str,
                'leds': emu.leds, 'relays': emu.relays,
                'plug': emu.plugged, 'door': emu.door_open,
                'af': emu.alarm_flags,
                'stop_reason': emu.stop_reason,
                'session_id': emu.session_id,
                'raw_ir': emu.raw_ir_cache,
                'jitter': emu.jitter_mode,
                'm_fail': emu.master_fail_sim,
                'm_alive': emu.master_alive,
                'a_limit': round(emu.current_limit/100.0, 1),
            }
        socketio.emit('update', data)
        save_counter += 1
        if save_counter >= 10:
            save_state(emulators)
            save_counter = 0
        socketio.sleep(1)

def run_server():
    def start_modbus():
        try:
            slaves = {}
            for i in SLAVE_IDS:
                slaves[i] = ModbusSlaveContext(
                    di=ModbusSequentialDataBlock(0, [0]*20),
                    co=ModbusSequentialDataBlock(0, [0]*20),
                    ir=ModbusSequentialDataBlock(0, [0]*512),  # lớn để không bao giờ out-of-range
                    hr=ModbusSequentialDataBlock(0, [0]*512),
                    zero_mode=True  # addr=0x0000 → block[0] khớp firmware STM32
                )
                emulators[i].context = slaves[i]
                # Load defaults vào HR (với zero_mode=True, addr trực tiếp = index)
                slaves[i].setValues(3, 0x0100, [450, 380, 750, 1200, 50, 300, 0, 1000, 0])
            server_context = ModbusServerContext(slaves=slaves, single=False)
            StartSerialServer(context=server_context, framer=ModbusRtuFramer,
                              port=PORT, baudrate=BAUDRATE,
                              parity='N', stopbits=1, bytesize=8, timeout=0.01)
        except Exception as e:
            with open("simulator_error.log", "a") as f:
                f.write(f"[{time.ctime()}] Modbus Error: {e}\n")

    socketio.start_background_task(background_task)
    threading.Thread(target=start_modbus, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)

if __name__ == "__main__": run_server()
