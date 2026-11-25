"""Niskopoziomowy protokół komunikacji z centralami Ropam serii Neo-IP.

Ten sam kanał TCP (port 9999), z którego korzysta aplikacja RopamNeo
w trybie lokalnym. Implementacja napisana od zera na potrzeby
interoperacyjności z własną centralą.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

DEFAULT_PORT = 9999

# Wektor używany przy wstępnym "przywitaniu" (48 bajtów z ID centrali).
HANDSHAKE_VECTOR = bytes(
    [34, 52, 68, 162, 244, 205, 91, 85, 33, 52, 67, 18, 152, 173, 36, 236]
)
# Klucz i wektor domyślny ramek przed zalogowaniem.
DEFAULT_KEY = b"aaaaaaaaaaaaaaaa"
DEFAULT_VECTOR = bytes(
    [4, 90, 118, 67, 90, 234, 45, 11, 123, 90, 87, 43, 98, 23, 123, 89]
)
HANDSHAKE_LEN = 48
HEADER_SIZE = 7
BRIDGE_INDEX = 0xFFFF
MAX_FRAME_LEN = 16384

# Typy ramek
T_LOGIN = 0
T_NSUPPORTED = 1
T_PING = 2
T_SETOUT = 3
T_SETOUTS = 4
T_GETCONFIG = 5
T_CONFIG = 6
T_ARM = 7
T_DISARM = 8
T_GETEVENTS = 9
T_EVENTS = 10
T_MESSAGE = 11
T_LOCKINPUTS = 12
T_LOGOUT = 13
T_ACK = 14
T_NACK = 15
T_STATUS = 16
T_RECONNECT = 17
T_EXT_STATUS = 40
T_PANIC = 42
T_SHUTTERS_CONFIG = 49
T_SILENT_CLOSE = 100

FRAME_NAMES = {
    0: "LOGIN",
    1: "NSUPPORTED",
    2: "PING",
    3: "SETOUT",
    4: "SETOUTS",
    5: "GETCONFIG",
    6: "CONFIG",
    7: "ARM",
    8: "DISARM",
    9: "GETEVENTS",
    10: "EVENTS",
    11: "MESSAGE",
    12: "LOCKINPUTS",
    13: "LOGOUT",
    14: "ACK",
    15: "NACK",
    16: "STATUS",
    17: "RECONNECT",
    18: "SMSVIRTUAL",
    19: "USSD",
    30: "CHECKACCESS",
    31: "READUSERNAMES",
    35: "SERVICECONNECT",
    39: "THERMOSTATPROFILE",
    40: "EXTSTATUS",
    41: "OPENWICKET",
    42: "PANIC",
    43: "FIRE",
    44: "USERCHANGE",
    45: "GETUSERMASK",
    46: "SENDMESSAGE",
    47: "SYNCUSERMASK",
    48: "SHUTTER",
    49: "SHUTTERSCONFIG",
    100: "SILENTCLOSE",
}

# Kody odpowiedzi logowania (pierwszy bajt danych ramki LOGIN)
LOGIN_RESULTS = {
    0: "ok",
    1: "nok",
    2: "no_permission",
    3: "bad_login",
    4: "bad_phone",
    5: "not_ready",
    6: "no_nightlines",
    7: "login_locked",
}


class ProtocolError(Exception):
    """Błąd protokołu."""


class BadFrameError(ProtocolError):
    """Ramka z błędną sumą kontrolną."""


def frame_name(ftype: int) -> str:
    return FRAME_NAMES.get(ftype, f"T{ftype}")


def vmpc(
    data: bytearray, start: int, end: int, key: bytes, vector: bytes, vlen: int = 16
) -> None:
    """Szyfrowanie/deszyfrowanie VMPC (operacja symetryczna, w miejscu)."""
    if end - start <= 0:
        return
    if not key:
        raise ProtocolError("Pusty klucz szyfrowania")
    p = list(range(256))
    s = 0
    klen = len(key)
    for i in range(768):
        n = i & 0xFF
        s = p[(s + p[n] + key[i % klen]) & 0xFF]
        p[n], p[s] = p[s], p[n]
    for i in range(768):
        n = i & 0xFF
        s = p[(s + p[n] + vector[i % vlen]) & 0xFF]
        p[n], p[s] = p[s], p[n]
    n = 0
    for i in range(start, end):
        s = p[(s + p[n]) & 0xFF]
        data[i] ^= p[(p[p[s]] + 1) & 0xFF]
        p[n], p[s] = p[s], p[n]
        n = (n + 1) & 0xFF


def crc8(data: bytes | bytearray, start: int, end: int) -> int:
    crc = 0
    for i in range(start, end):
        b = data[i]
        for _ in range(8):
            if (b ^ crc) & 1:
                crc = (((crc ^ 0x18) >> 1) | 0x80) & 0xFF
            else:
                crc >>= 1
            b >>= 1
    return crc


def _frame_vector(index_bytes: bytes, base_vector: bytes) -> bytes:
    return bytes(index_bytes[0:2]) + bytes(base_vector[2:16])


def build_handshake(device_id: str, rnd: bytes) -> bytes:
    """48 bajtów wysyłane zaraz po połączeniu TCP."""
    idb = device_id.encode("latin-1", errors="replace")
    buf = bytearray(HANDSHAKE_LEN)
    for i, b in enumerate(idb[:HANDSHAKE_LEN]):
        buf[i] = b
    for i in range(16, HANDSHAKE_LEN):
        buf[i] = rnd[(i - 16) % len(rnd)]
    vmpc(buf, 0, HANDSHAKE_LEN, idb, HANDSHAKE_VECTOR)
    return bytes(buf)


def encode_frame(
    index: int, ftype: int, data: bytes, key: bytes, base_vector: bytes
) -> bytes:
    length = len(data)
    buf = bytearray(HEADER_SIZE + length)
    struct.pack_into("<HH", buf, 0, index & 0xFFFF, length)
    buf[4] = ftype & 0xFF
    buf[5 : 5 + length] = data
    buf[5 + length] = crc8(buf, 4, 5 + length)
    vmpc(buf, 4, 6 + length, key, _frame_vector(buf[0:2], base_vector))
    buf[6 + length] = crc8(buf, 0, 6 + length)
    return bytes(buf)


@dataclass
class Frame:
    index: int
    ftype: int
    data: bytes
    crc_ok: bool = True

    @property
    def name(self) -> str:
        return frame_name(self.ftype)

    def text(self) -> str:
        return decode_text(self.data)


def decode_frame(raw: bytes, key: bytes, base_vector: bytes) -> Frame:
    buf = bytearray(raw)
    index, length = struct.unpack_from("<HH", buf, 0)
    if len(buf) < HEADER_SIZE + length:
        raise ProtocolError("Za krótka ramka")
    crc2_ok = buf[6 + length] == crc8(buf, 0, 6 + length)
    if index == BRIDGE_INDEX:
        # Ramki serwera pośredniczącego - w trybie lokalnym nie występują.
        vmpc(buf, 13, 6 + length, key, _frame_vector(buf[0:2], base_vector))
        data = bytes(buf[13 : 13 + max(0, length - 8)])
        return Frame(index, buf[4], data, True)
    vmpc(buf, 4, 6 + length, key, _frame_vector(buf[0:2], base_vector))
    crc1_ok = buf[5 + length] == crc8(buf, 4, 5 + length)
    return Frame(index, buf[4], bytes(buf[5 : 5 + length]), crc1_ok and crc2_ok)


def decode_text(data: bytes) -> str:
    end = data.find(b"\x00")
    if end >= 0:
        data = data[:end]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1250", errors="replace")


# --------------------------------------------------------------------------
# Status

INPUT_STATES = {
    "0": "ok",
    "1": "violated",
    "!": "tamper",
    "X": "disabled",
    "b": "locked",
    "B": "locked",
    "f": "failure",
    "F": "failure",
    "a": "alarm_memory",
    "A": "alarm_memory_violated",
    "w": "low_battery",
    "W": "low_battery_violated",
    "?": "link_failure",
    "i": "analog",
}
INPUT_ACTIVE = {"1", "A", "W"}

OUTPUT_STATES = {
    "0": "off",
    "1": "on",
    "F": "failure_on",
    "f": "failure_off",
    "X": "no_control_on",
    "x": "no_control_off",
    "N": "no_control_failure_on",
    "n": "no_control_failure_off",
}
OUTPUT_ON = {"1", "F", "X", "N"}
OUTPUT_CONTROLLABLE = {"0", "1", "F", "f"}


@dataclass
class ZoneStatus:
    armed: bool = False
    night: bool = False
    exit_delay: bool = False
    entry_delay: bool = False
    alarm: bool = False
    tamper: bool = False
    ready: bool = False
    timer: int | None = None
    raw: int = 0


@dataclass
class NeoStatus:
    raw: str
    hardware: str = ""
    firmware: str = ""
    lang: str = ""
    module_time: str | None = None
    inputs: str = ""
    outputs: str = ""
    zones: list[ZoneStatus] = field(default_factory=list)
    temperatures: list[float | None] = field(default_factory=list)
    temp_errors: list[str] = field(default_factory=list)
    ac_ok: bool | None = None
    supply_voltage: float | None = None
    network_status: int | None = None
    wifi_status: int | None = None
    fail_codes: int | None = None
    analog_value: float | None = None
    analog_unit: str | None = None
    device_mode: str | None = None
    humidity: list[int | None] = field(default_factory=list)
    parse_error: str | None = None

    def input_char(self, idx: int) -> str:
        return self.inputs[idx] if idx < len(self.inputs) else "-"

    def output_char(self, idx: int) -> str:
        return self.outputs[idx] if idx < len(self.outputs) else "-"

    def as_dict(self) -> dict[str, Any]:
        return {
            "hardware": self.hardware,
            "firmware": self.firmware,
            "lang": self.lang,
            "module_time": self.module_time,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "zones": [z.__dict__ for z in self.zones],
            "temperatures": self.temperatures,
            "temp_errors": self.temp_errors,
            "ac_ok": self.ac_ok,
            "supply_voltage": self.supply_voltage,
            "network_status": self.network_status,
            "wifi_status": self.wifi_status,
            "fail_codes": self.fail_codes,
            "analog_value": self.analog_value,
            "analog_unit": self.analog_unit,
            "device_mode": self.device_mode,
            "humidity": self.humidity,
            "parse_error": self.parse_error,
        }


def parse_status(text: str) -> NeoStatus:
    """Parsuje tekstowy status centrali. Toleruje obcięty/inny format."""
    st = NeoStatus(raw=text)
    if not text or text[0] not in "#%":
        st.parse_error = "zły prefiks"
        return st
    pos = 1

    def take(n: int) -> str:
        nonlocal pos
        if pos + n > len(text):
            raise ValueError(f"koniec danych na pozycji {pos}")
        s = text[pos : pos + n]
        pos += n
        return s

    try:
        st.hardware = take(1)
        fw = take(2)
        st.firmware = f"{fw[0]}.{fw[1]}"
        st.lang = take(1)
        mt = take(10)
        if mt[:2] != "00":
            try:
                st.module_time = datetime.strptime(mt, "%y%m%d%H%M").isoformat()
            except ValueError:
                st.module_time = mt
        st.inputs = take(32)
        st.outputs = take(32)
        for _ in range(2):
            b = int(take(2), 16)
            st.zones.append(
                ZoneStatus(
                    armed=bool(b & 1),
                    night=bool(b >> 1 & 1),
                    exit_delay=bool(b >> 2 & 1),
                    entry_delay=bool(b >> 3 & 1),
                    alarm=bool(b >> 4 & 1),
                    tamper=bool(b >> 5 & 1),
                    ready=bool(b >> 6 & 1),
                    raw=b,
                )
            )
        for i in range(2):
            st.zones[i].timer = int(take(4), 16)
        for _ in range(2):
            s = take(4)
            if s == "!!!!":
                st.temperatures.append(None)
                st.temp_errors.append("error")
            elif s.lower() == "xxxx":
                st.temperatures.append(None)
                st.temp_errors.append("none")
            else:
                v = int(s, 16)
                if v >= 0x8000:
                    v -= 0x10000
                st.temperatures.append(v / 10)
                st.temp_errors.append("")
        st.ac_ok = take(1) == "0"
        st.supply_voltage = int(take(2), 16) / 10
        st.network_status = int(take(1), 16)
        st.wifi_status = int(take(1), 16)
        st.fail_codes = int(take(16), 16)
        ai = int(take(8), 16)
        st.analog_value = round(struct.unpack("<f", struct.pack("<I", ai))[0], 3)
        st.analog_unit = take(2).strip()
        st.device_mode = {"d": "day", "n": "night", "s": "service"}.get(take(1))
        take(2)  # flagi połączeń (bridge/lokalne/RMS)
        for _ in range(2):
            h = int(take(2), 16)
            st.humidity.append(None if h >= 254 else h)
    except (ValueError, IndexError) as err:
        st.parse_error = str(err)
    return st


def parse_config(text: str) -> dict[str, Any]:
    try:
        cfg = json.loads(text)
    except ValueError as err:
        raise ProtocolError(f"Niepoprawny JSON konfiguracji: {err}") from err
    if not isinstance(cfg, dict):
        raise ProtocolError("Konfiguracja nie jest obiektem JSON")
    return cfg


def output_mask(count: int, index: int, on: bool) -> bytes:
    """Maska dla ramki SETOUTS: 'x' = bez zmian, '1'/'0' = załącz/wyłącz."""
    mask = ["x"] * count
    mask[index] = "1" if on else "0"
    return "".join(mask).encode("ascii")
