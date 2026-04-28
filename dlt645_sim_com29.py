#!/usr/bin/env python3
"""
DLT645-2007 Meter Simulator — Full Spec
COM29 | 2400 baud | 8N1 (switches to 8E1 for TX to match MCU behavior)

Supported Data Identifiers (from dlt645_meter.h):
  DLT_DI_VOLTAGE  0x02010100  Phase A Voltage  XXX.X V      (2 bytes)
  DLT_DI_CURRENT  0x02020100  Phase A Current  XXX.XXX A    (3 bytes)
  DLT_DI_POWER    0x02030000  Total Active Pwr XX.XXXX kW   (3 bytes)
  DLT_DI_POWER_A  0x02030100  Phase A Pwr      XX.XXXX kW   (3 bytes)
  DLT_DI_ENERGY   0x00010000  Total Fwd Energy XXXXXX.XX kWh(4 bytes)
  DLT_DI_FREQ     0x02800002  Grid Frequency   XX.XX Hz     (2 bytes)
  DLT_DI_PF       0x02060000  Total PF         X.XXX        (2 bytes)
  DLT_DI_PF_A     0x02060100  Phase A PF       X.XXX        (2 bytes)
  DLT_CMD_READ_ADDR 0x13      Read Meter Address
"""

import serial
import time
import random
import math

# ─── Config ──────────────────────────────────────────────────────────────────
PORT  = 'COM29'
BAUD  = 2400
ADDR  = [0x11, 0x22, 0x33, 0x44, 0x55, 0x66]  # BCD: meter SN 665544332211

# ─── Data Identifiers (DI) — must match firmware header ──────────────────────
DLT_DI_VOLTAGE  = 0x02010100
DLT_DI_CURRENT  = 0x02020100
DLT_DI_POWER    = 0x02030000
DLT_DI_POWER_A  = 0x02030100
DLT_DI_ENERGY   = 0x00010000
DLT_DI_FREQ     = 0x02800002
DLT_DI_PF       = 0x02060000
DLT_DI_PF_A     = 0x02060100

DLT_CMD_READ      = 0x11
DLT_CMD_READ_ADDR = 0x13
DLT_RESP_OK       = 0x91
DLT_RESP_ADDR_OK  = 0x93


# ─── BCD Encoding Helpers ─────────────────────────────────────────────────────
def _dec_to_bcd(val: int) -> int:
    """Single byte: decimal 0-99 → BCD (e.g. 23 → 0x23)"""
    return ((val // 10) & 0xF) << 4 | (val % 10)

def encode_bcd_le(int_val: int, num_bytes: int) -> list:
    """
    Encode integer as BCD, little-endian, with +0x33 offset.
    Each byte covers 2 decimal digits.
    e.g. 2203 → [0x36, 0x55] (2 bytes)
    """
    result = []
    for _ in range(num_bytes):
        digit_pair = int_val % 100
        bcd_byte   = _dec_to_bcd(digit_pair)
        result.append((bcd_byte + 0x33) & 0xFF)
        int_val //= 100
    return result

def parse_di(frame_bytes: bytes, di_offset: int) -> int:
    """
    Read 4 bytes from frame starting at di_offset,
    subtract 0x33 from each, reconstruct uint32 LE.
    """
    raw = [(frame_bytes[di_offset + k] - 0x33) & 0xFF for k in range(4)]
    return raw[0] | (raw[1] << 8) | (raw[2] << 16) | (raw[3] << 24)


# ─── Physics Model ────────────────────────────────────────────────────────────
class MeterPhysics:
    """
    Simulates a single-phase AC meter attached to an EV charger.
    Charging cycle: ramp-up → constant → taper → idle.
    """
    CYCLE = 120.0  # seconds per charge pseudo-cycle

    def __init__(self):
        self.t0        = time.time()
        self.energy    = 128340.0   # kWh — starting cumulative energy

    def _phase(self, t: float) -> float:
        """Returns 0–1 charge phase from cycle position."""
        pos = (t % self.CYCLE) / self.CYCLE
        if pos < 0.2:  # ramp
            return pos / 0.2
        elif pos < 0.7:  # constant
            return 1.0
        else:           # taper
            return max(0.0, 1.0 - (pos - 0.7) / 0.3)

    def snapshot(self) -> dict:
        t_elapsed = time.time() - self.t0
        phase     = self._phase(t_elapsed)

        # Voltage: 218–224V jitter
        v_noise   = random.gauss(0, 0.3)
        voltage   = round(220.5 + v_noise + phase * 1.2, 1)      # V

        # Current: 0–16A based on phase
        i_noise   = random.gauss(0, 0.05)
        current   = round(max(0.0, 16.0 * phase + i_noise), 3)   # A

        # Power (kW)
        power     = round(voltage * current / 1000.0, 4)          # kW

        # Frequency: 49.95–50.05 Hz
        freq      = round(50.0 + random.gauss(0, 0.02), 2)       # Hz

        # Power factor: 0.95–0.99 during charge, 1.0 idle
        pf        = round(0.97 + (0.02 if phase > 0.05 else 0.03) * random.gauss(1, 0.01), 3)
        pf        = min(1.0, max(0.90, pf))

        # Accumulate energy (kWh per real second)
        dt = 1.0  # called ~1/s
        self.energy += (power * dt) / 3600.0

        return {
            'voltage': voltage,
            'current': current,
            'power':   power,
            'energy':  round(self.energy, 2),
            'freq':    freq,
            'pf':      pf,
        }


# ─── Frame Builder ────────────────────────────────────────────────────────────
def build_response(di: int, data_bytes: list) -> bytes:
    """
    Build a DLT645-2007 response frame:
    [FE FE FE FE] 68 <ADDR[6]> 68 91 <L> <DI+0x33 x4> <data> <CS> 16
    """
    di_enc = encode_bcd_le(                # DI as 4 bytes with +0x33, LSB first
        ((di & 0xFF)) |
        (((di >> 8) & 0xFF) << 8) |
        (((di >> 16) & 0xFF) << 16) |
        (((di >> 24) & 0xFF) << 24),
        4
    )
    # Actually encode DI bytes directly with +0x33
    di_wire = [
        ((di & 0xFF) + 0x33) & 0xFF,
        (((di >> 8)  & 0xFF) + 0x33) & 0xFF,
        (((di >> 16) & 0xFF) + 0x33) & 0xFF,
        (((di >> 24) & 0xFF) + 0x33) & 0xFF,
    ]
    L = 4 + len(data_bytes)
    payload = [0x68] + ADDR + [0x68, DLT_RESP_OK, L] + di_wire + data_bytes
    cs = sum(payload) % 256
    return bytes([0xFE, 0xFE, 0xFE, 0xFE] + payload + [cs, 0x16])

def build_addr_response() -> bytes:
    """Response to CMD 0x13 (Read Address)."""
    payload = [0x68] + ADDR + [0x68, DLT_RESP_ADDR_OK, 0x06] + ADDR
    cs = sum(payload) % 256
    return bytes([0xFE, 0xFE, 0xFE, 0xFE] + payload + [cs, 0x16])


# ─── Data Encode per DI ───────────────────────────────────────────────────────
def encode_for_di(di: int, snap: dict) -> list | None:
    """Return BCD-encoded wire bytes for a given DI, or None if unknown."""

    if di == DLT_DI_VOLTAGE:
        # XXX.X V → ×10, 2 bytes
        return encode_bcd_le(round(snap['voltage'] * 10), 2)

    elif di == DLT_DI_CURRENT:
        # XXX.XXX A → ×1000, 3 bytes
        return encode_bcd_le(round(snap['current'] * 1000), 3)

    elif di in (DLT_DI_POWER, DLT_DI_POWER_A):
        # XX.XXXX kW → ×10000, 3 bytes
        return encode_bcd_le(round(snap['power'] * 10000), 3)

    elif di == DLT_DI_ENERGY:
        # XXXXXX.XX kWh → ×100, 4 bytes
        return encode_bcd_le(round(snap['energy'] * 100), 4)

    elif di == DLT_DI_FREQ:
        # XX.XX Hz → ×100, 2 bytes
        return encode_bcd_le(round(snap['freq'] * 100), 2)

    elif di in (DLT_DI_PF, DLT_DI_PF_A):
        # X.XXX → ×1000, 2 bytes
        return encode_bcd_le(round(snap['pf'] * 1000), 2)

    return None


DI_NAMES = {
    DLT_DI_VOLTAGE:  'VOLTAGE',
    DLT_DI_CURRENT:  'CURRENT',
    DLT_DI_POWER:    'POWER(total)',
    DLT_DI_POWER_A:  'POWER(A)',
    DLT_DI_ENERGY:   'ENERGY',
    DLT_DI_FREQ:     'FREQUENCY',
    DLT_DI_PF:       'PF(total)',
    DLT_DI_PF_A:     'PF(A)',
}


# ─── Main Loop ────────────────────────────────────────────────────────────────
def open_port(parity):
    return serial.Serial(PORT, BAUD, parity=parity,
                         bytesize=8, stopbits=1, timeout=0.2)

def main():
    print("=" * 60)
    print(f"  DLT645-2007 Full Simulator — {PORT} @ {BAUD} baud")
    print(f"  Meter Address : {''.join(f'{x:02X}' for x in ADDR[::-1])}")
    print(f"  Supports      : V / I / P / E / Hz / PF")
    print("=" * 60)

    try:
        ser = open_port(serial.PARITY_NONE)
    except Exception as e:
        print(f"  [ERR] Cannot open {PORT}: {e}")
        return

    meter = MeterPhysics()
    snap  = meter.snapshot()   # initial snapshot
    last_snap = time.time()

    buf = b''
    while True:
        try:
            # Refresh physics ~1/s
            if time.time() - last_snap >= 1.0:
                snap = meter.snapshot()
                last_snap = time.time()
                print(f"  [{time.strftime('%H:%M:%S')}] "
                      f"V={snap['voltage']:.1f}V  "
                      f"I={snap['current']:.3f}A  "
                      f"P={snap['power']:.3f}kW  "
                      f"E={snap['energy']:.2f}kWh  "
                      f"Hz={snap['freq']:.2f}  "
                      f"PF={snap['pf']:.3f}")

            # Accumulate bytes
            if ser.in_waiting > 0:
                buf += ser.read(ser.in_waiting)

            # Hunt for frame start 0x68
            while buf and buf[0] != 0x68:
                if buf[0] == 0xFE:   # skip preamble bytes
                    buf = buf[1:]
                else:
                    buf = buf[1:]

            if len(buf) < 12:
                time.sleep(0.02)
                continue

            # Validate second 0x68
            if buf[7] != 0x68:
                buf = buf[1:]
                continue

            ctrl = buf[8]
            L    = buf[9]
            frame_end = 10 + L + 2  # ... + CS + 0x16

            if len(buf) < frame_end:
                time.sleep(0.02)
                continue

            if buf[frame_end - 1] != 0x16:
                buf = buf[1:]
                continue

            frame = buf[:frame_end]
            buf   = buf[frame_end:]

            print(f"  [RX] {frame.hex().upper()}")

            # ── TX: switch to EVEN parity (MCU expects 8E1 response) ──
            ser.close()
            ser = open_port(serial.PARITY_EVEN)
            time.sleep(0.01)

            if ctrl == DLT_CMD_READ_ADDR:
                resp = build_addr_response()
                ser.write(resp)
                print(f"  [TX] READ_ADDR  -> {resp.hex().upper()}")

            elif ctrl == DLT_CMD_READ:
                if L < 4:
                    print("  [!!] Frame too short for DI")
                else:
                    di = parse_di(frame, 10)
                    di_name = DI_NAMES.get(di, f"0x{di:08X}")
                    data_bytes = encode_for_di(di, snap)

                    if data_bytes is not None:
                        resp = build_response(di, data_bytes)
                        ser.write(resp)
                        print(f"  [TX] {di_name:<14} -> {resp.hex().upper()}")
                    else:
                        print(f"  [!!] Unknown DI 0x{di:08X} — no response")
            else:
                print(f"  [!!] Unknown CMD 0x{ctrl:02X} — ignored")

            # ── Switch back to NONE parity for RX ──
            time.sleep(0.01)
            ser.close()
            ser = open_port(serial.PARITY_NONE)

        except serial.SerialException as e:
            print(f"  [ERR] Serial: {e}. Reconnecting...")
            time.sleep(2)
            try:
                ser.close()
            except: pass
            try:
                ser = open_port(serial.PARITY_NONE)
            except Exception as e2:
                print(f"  [ERR] {e2}")
        except Exception as e:
            print(f"  [ERR] {e}")
            time.sleep(0.5)


if __name__ == "__main__":
    main()
