"""Symulator centrali Ropam Neo-IP do testów protokołu (po stronie centrali)."""
import asyncio, json, os, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "ropam_neo"))
import protocol as P

DEVICE_ID = "TESTID0000000001"
TCP_KEY = "testtcpkey000001"
CODE = "1234"


class Central:
    def __init__(self):
        self.inputs = list("10000000" + "-" * 24)
        self.outputs = list("01xX0000" + "-" * 24)
        self.zones = [0x40, 0x40]
        self.received = []

    def status_text(self):
        s = "#7" + "38" + "p" + "2611242035"
        s += "".join(self.inputs) + "".join(self.outputs)
        s += "".join(f"{z:02X}" for z in self.zones)
        s += "0000" * 2
        s += "00E6" + "xxxx"          # 23.0 °C, brak
        s += "0" + "8A" + "1" + "2"   # AC ok, 13.8 V, net, wifi
        s += "0" * 16
        s += struct.unpack("<I", struct.pack("<f", 12.5))[0].to_bytes(4, "big").hex().upper() + "V "
        s += "d" + "05" + "FEFF" + "00" + "00"
        return s


async def handle(reader, writer, c: Central, mode="ok"):
    hs = bytearray(await reader.readexactly(48))
    P.vmpc(hs, 0, 48, DEVICE_ID.encode(), P.HANDSHAKE_VECTOR)
    if bytes(hs[:16]) != DEVICE_ID.encode():
        writer.write(bytes([2]) + bytes(47)); await writer.drain(); writer.close(); return
    writer.write(bytes([0, 0, 0, 0, 0, 0, 192, 168, 1, 50]) + bytes(38)); await writer.drain()
    key = TCP_KEY.encode()
    vec = P.DEFAULT_VECTOR
    idx = [0]

    async def recv(v):
        head = await reader.readexactly(4)
        ln = struct.unpack_from("<H", head, 2)[0]
        rest = await reader.readexactly(ln + 3)
        return P.decode_frame(head + rest, key, v)

    def send(t, data, v):
        idx[0] += 2
        writer.write(P.encode_frame(idx[0], t, data, key, v))

    f = await recv(vec)
    if not f.crc_ok:
        writer.close(); return
    assert f.ftype == P.T_LOGIN
    code = f.data[:-20].decode(); ipb = f.data[-20:-16]; rnd = f.data[-16:]
    assert ipb == bytes([192, 168, 1, 50]), ipb
    new_vec = os.urandom(16)
    if code != CODE:
        send(P.T_LOGIN, bytes([3]) + bytes(52), rnd); await writer.drain(); return
    send(P.T_LOGIN, bytes([0, 2, 0b10011]) + new_vec + b"\x34\x12" + b"X" * 32, rnd)
    await writer.drain()
    vec = new_vec
    send(P.T_STATUS, c.status_text().encode(), vec); await writer.drain()
    while True:
        try:
            f = await asyncio.wait_for(recv(vec), 5)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            break
        c.received.append((f.ftype, f.data))
        if f.ftype == P.T_GETCONFIG:
            cfg = {"deviceID": DEVICE_ID, "phone": "+48000000000", "zones": ["Dom", "Garaż"],
                   "inputs": ["PIR salon", "Kontaktron drzwi", "", "", "", "", "", ""],
                   "outputs": ["Syrena", "Brama", "Światło", "LED"], "temps": ["Kotłownia"], "analog": "Akumulator"}
            send(P.T_CONFIG, json.dumps(cfg, ensure_ascii=False).encode(), vec)
        elif f.ftype == P.T_ARM:
            mask, night = f.data[0], f.data[1]
            for z in range(2):
                if mask >> z & 1:
                    c.zones[z] = 0x40 | 1 | (2 if night else 0)
            send(P.T_ARM, b"\x00", vec); send(P.T_STATUS, c.status_text().encode(), vec)
        elif f.ftype == P.T_DISARM:
            mask = f.data[0]
            for z in range(2):
                if mask >> z & 1:
                    c.zones[z] = 0x40
            send(P.T_DISARM, b"\x00", vec); send(P.T_STATUS, c.status_text().encode(), vec)
        elif f.ftype == P.T_SETOUTS:
            m = f.data.decode()
            for i, ch in enumerate(m):
                if ch in "01" and c.outputs[i] in "01":
                    c.outputs[i] = ch
            send(P.T_STATUS, c.status_text().encode(), vec)
        elif f.ftype == P.T_PANIC:
            c.zones[0] |= 0x10
            send(P.T_PANIC, b"", vec); send(P.T_STATUS, c.status_text().encode(), vec)
        elif f.ftype == P.T_PING:
            send(P.T_PING, b"", vec)
        elif f.ftype == P.T_LOGOUT:
            break
        await writer.drain()
    writer.close()
