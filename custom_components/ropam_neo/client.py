"""Klient asyncio dla central Ropam Neo-IP (lokalnie, port 9999)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .protocol import (
    DEFAULT_KEY,
    DEFAULT_VECTOR,
    HANDSHAKE_LEN,
    LOGIN_RESULTS,
    MAX_FRAME_LEN,
    T_ACK,
    T_ARM,
    T_CONFIG,
    T_DISARM,
    T_EVENTS,
    T_EXT_STATUS,
    T_GETCONFIG,
    T_LOGIN,
    T_LOGOUT,
    T_MESSAGE,
    T_NACK,
    T_PANIC,
    T_PING,
    T_SETOUTS,
    T_SILENT_CLOSE,
    T_STATUS,
    BadFrameError,
    Frame,
    NeoStatus,
    ProtocolError,
    build_handshake,
    decode_frame,
    encode_frame,
    frame_name,
    output_mask,
    parse_config,
    parse_status,
)

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 8
LOGIN_TIMEOUT = 6
IDLE_TIMEOUT = 45
PING_INTERVAL = 20
TEXT_LIMIT = 4000


class NeoError(Exception):
    """Ogólny błąd klienta."""

    code = "unknown"


class CannotConnect(NeoError):
    code = "cannot_connect"


class DeviceBusy(NeoError):
    code = "busy"


class BadDialog(NeoError):
    code = "bad_dialog"


class BadTcpKey(NeoError):
    code = "bad_tcp_key"


class LoginRejected(NeoError):
    """Centrala odrzuciła logowanie (kod w atrybucie result)."""

    def __init__(self, result: int) -> None:
        self.result = result
        self.code = {
            2: "no_permission",
            3: "invalid_auth",
            7: "login_locked",
        }.get(result, "login_rejected")
        super().__init__(f"Logowanie odrzucone: {LOGIN_RESULTS.get(result, result)}")


@dataclass
class LoginInfo:
    user_no: int = 0
    zone1: bool = False
    zone2: bool = False
    remote: bool = False
    can_lock_inputs: bool = False
    settings_crc: int = 0

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class LogEntry:
    ts: float
    kind: str  # TX / RX / INFO / ERR
    text: str

    def as_dict(self) -> dict[str, Any]:
        return {"ts": self.ts, "kind": self.kind, "text": self.text}


@dataclass
class NeoState:
    connected: bool = False
    status: NeoStatus | None = None
    config: dict[str, Any] | None = None
    config_raw: str | None = None
    ext_status_raw: str | None = None
    login: LoginInfo | None = None
    last_frame: float | None = None
    last_error: str | None = None
    last_message: str | None = None
    last_message_time: float | None = None
    connects: int = 0
    events: list[str] = field(default_factory=list)


class RopamNeoClient:
    """Utrzymuje połączenie z centralą i udostępnia stan."""

    def __init__(
        self,
        host: str,
        port: int,
        device_id: str,
        tcp_key: str,
        user_code: str,
        log_size: int = 300,
    ) -> None:
        self.host = host
        self.port = port
        self.device_id = device_id.strip()
        self.tcp_key = tcp_key.strip()
        self.user_code = user_code.strip()
        self.state = NeoState()
        self.log: deque[LogEntry] = deque(maxlen=log_size)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._key = DEFAULT_KEY
        self._vector = DEFAULT_VECTOR
        self._index = 1
        self._write_lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._listeners: list[Callable[[], None]] = []
        self._message_listeners: list[Callable[[str], None]] = []
        self._ready = asyncio.Event()

    # ------------------------------------------------------------ public API

    @property
    def connected(self) -> bool:
        return self.state.connected

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    def add_message_listener(self, cb: Callable[[str], None]) -> Callable[[], None]:
        self._message_listeners.append(cb)
        return lambda: (
            self._message_listeners.remove(cb)
            if cb in self._message_listeners
            else None
        )

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.get_running_loop().create_task(
                self._run(), name="ropam_neo_client"
            )

    async def stop(self) -> None:
        self._stopping = True
        if self._writer is not None and self.state.connected:
            try:
                await asyncio.wait_for(self._send(T_LOGOUT, b""), 2)
            except Exception:  # noqa: BLE001
                pass
        await self._close()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def wait_ready(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._ready.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def async_test(self, timeout: float = 12) -> LoginInfo:
        """Jednorazowe połączenie + logowanie (dla formularza konfiguracji)."""
        try:
            info = await asyncio.wait_for(self._connect_and_login(), timeout)
            try:
                await asyncio.wait_for(self._send(T_LOGOUT, b""), 2)
            except Exception:  # noqa: BLE001
                pass
            return info
        except asyncio.TimeoutError as err:
            raise CannotConnect("Przekroczono czas połączenia") from err
        finally:
            await self._close()

    def clear_log(self) -> None:
        self.log.clear()
        self._info("Log wyczyszczony")

    async def arm(self, zone_mask: int, night: bool = False) -> None:
        data = bytes([zone_mask & 0xFF, 1 if night else 0]) + self.user_code.encode()
        await self._send(
            T_ARM,
            data,
            log_text=f"strefy=0b{zone_mask:02b} {'nocne' if night else 'pełne'} kod=****",
        )

    async def disarm(self, zone_mask: int) -> None:
        data = bytes([zone_mask & 0xFF]) + self.user_code.encode()
        await self._send(T_DISARM, data, log_text=f"strefy=0b{zone_mask:02b} kod=****")

    async def set_output(self, index: int, on: bool) -> None:
        count = 32
        if self.state.status and len(self.state.status.outputs) > count:
            count = len(self.state.status.outputs)
        mask = output_mask(count, index, on)
        await self._send(T_SETOUTS, mask, log_text=mask.decode())

    async def panic(self) -> None:
        """Alarm napadowy (jak przycisk PANIC w aplikacji RopamNeo)."""
        await self._send(T_PANIC, b"", log_text="ALARM NAPADOWY")

    async def request_config(self) -> None:
        await self._send(T_GETCONFIG, b"")

    # ------------------------------------------------------------ internals

    def _add_log(self, kind: str, text: str) -> None:
        if len(text) > TEXT_LIMIT:
            text = text[:TEXT_LIMIT] + f"… (+{len(text) - TEXT_LIMIT} znaków)"
        self.log.append(LogEntry(time.time(), kind, text))

    def _info(self, text: str) -> None:
        self._add_log("INFO", text)
        _LOGGER.debug(text)

    def _err(self, text: str) -> None:
        self._add_log("ERR", text)
        _LOGGER.debug(text)

    def _notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Błąd listenera")

    def _next_index(self) -> int:
        self._index = (self._index + 2) & 0xFFFF
        if self._index == 0xFFFF:
            self._index = 1
        return self._index

    async def _close(self) -> None:
        writer = self._writer
        self._writer = None
        self._reader = None
        if writer is not None:
            try:
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), 2)
            except Exception:  # noqa: BLE001
                pass
        if self.state.connected:
            self.state.connected = False
            self._notify()

    async def _send(
        self, ftype: int, data: bytes, log_text: str | None = None
    ) -> None:
        if self._writer is None:
            raise CannotConnect("Brak połączenia z centralą")
        async with self._write_lock:
            raw = encode_frame(self._next_index(), ftype, data, self._key, self._vector)
            if log_text is None:
                log_text = data.hex(" ") if data else ""
            self._add_log(
                "TX", f"{frame_name(ftype)}({ftype}) len={len(data)} {log_text}".rstrip()
            )
            self._writer.write(raw)
            await self._writer.drain()

    async def _read_exact(self, n: int, timeout: float) -> bytes:
        if self._reader is None:
            raise CannotConnect("Brak połączenia")
        try:
            return await asyncio.wait_for(self._reader.readexactly(n), timeout)
        except asyncio.IncompleteReadError as err:
            raise CannotConnect("Centrala zamknęła połączenie") from err

    async def _recv_frame(self, timeout: float) -> Frame:
        head = await self._read_exact(4, timeout)
        length = struct.unpack_from("<H", head, 2)[0]
        if length > MAX_FRAME_LEN:
            raise ProtocolError(f"Nieprawidłowa długość ramki {length}")
        rest = await self._read_exact(length + 3, timeout)
        frame = decode_frame(head + rest, self._key, self._vector)
        self.state.last_frame = time.time()
        if not frame.crc_ok:
            self._err(f"Zła suma kontrolna ramki (typ {frame.ftype}, len {length})")
            raise BadFrameError("crc")
        return frame

    async def _connect_and_login(self) -> LoginInfo:
        if not self.device_id:
            raise NeoError("Brak ID centrali")
        self._key = DEFAULT_KEY
        self._vector = DEFAULT_VECTOR
        self._info(f"Łączę z {self.host}:{self.port}")
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), CONNECT_TIMEOUT
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise CannotConnect(f"Nie można połączyć: {err}") from err

        # 1) powitanie z ID centrali
        self._writer.write(build_handshake(self.device_id, os.urandom(32)))
        await self._writer.drain()
        resp = await self._read_exact(HANDSHAKE_LEN, LOGIN_TIMEOUT)
        self._info(f"Powitanie: odpowiedź {resp[0]} ({resp[:10].hex(' ')})")
        if resp[0] == 1:
            raise DeviceBusy("Centrala zajęta (inne połączenie)")
        if resp[0] != 0:
            raise BadDialog(f"Nieoczekiwana odpowiedź powitania: {resp[0]}")
        ip_bytes = bytes(resp[6:10])

        # 2) logowanie (do 3 prób jak w aplikacji)
        frame: Frame | None = None
        bad_frame = False
        for attempt in range(3):
            frame, bad = await self._try_login(ip_bytes)
            bad_frame = bad_frame or bad
            if frame is not None and frame.ftype == T_LOGIN:
                break
            await asyncio.sleep(0.5)
        if frame is None or frame.ftype != T_LOGIN or not frame.data:
            if bad_frame:
                raise BadTcpKey("Centrala nie rozumie ramek - zły klucz TCP/IP?")
            raise BadDialog("Brak odpowiedzi na logowanie")
        result = frame.data[0]
        self._info(f"Logowanie: wynik {result} ({LOGIN_RESULTS.get(result, '?')})")
        if result != 0:
            raise LoginRejected(result)
        d = frame.data
        if len(d) < 21:
            raise BadDialog(f"Za krótka odpowiedź logowania ({len(d)} B)")
        perms = d[2]
        info = LoginInfo(
            user_no=d[1],
            zone1=bool(perms & 1),
            zone2=bool(perms >> 1 & 1),
            remote=bool(perms >> 4 & 1),
            can_lock_inputs=bool(perms >> 5 & 1),
            settings_crc=struct.unpack_from("<H", d, 19)[0],
        )
        self._vector = bytes(d[3:19])
        self._info(
            f"Zalogowano jako użytkownik {info.user_no} "
            f"(strefa1={info.zone1}, strefa2={info.zone2}, zdalnie={info.remote})"
        )
        return info

    async def _try_login(self, ip_bytes: bytes) -> tuple[Frame | None, bool]:
        # ramka logowania: klucz TCP/IP centrali + wektor domyślny
        self._key = self.tcp_key.encode("utf-8")
        self._vector = DEFAULT_VECTOR
        rnd = os.urandom(16)
        data = self.user_code.encode("utf-8") + ip_bytes + rnd
        await self._send(T_LOGIN, data, log_text="kod=**** + losowe")
        self._vector = rnd
        bad = False
        for _ in range(4):
            try:
                frame = await self._recv_frame(LOGIN_TIMEOUT)
            except BadFrameError:
                bad = True
                continue
            except asyncio.TimeoutError:
                return None, bad
            except CannotConnect as err:
                raise BadTcpKey(
                    "Centrala rozłączyła się zaraz po logowaniu - "
                    "najpewniej zły klucz TCP/IP"
                ) from err
            self._add_log("RX", f"{frame.name}({frame.ftype}) len={len(frame.data)}")
            if frame.ftype == T_LOGIN and len(frame.data) >= 53:
                return frame, bad
            if frame.ftype == T_LOGIN and frame.data and frame.data[0] != 0:
                return frame, bad
        return None, bad

    async def _run(self) -> None:
        backoff = 5
        while not self._stopping:
            ping_task: asyncio.Task | None = None
            try:
                info = await self._connect_and_login()
                self.state.login = info
                self.state.connected = True
                self.state.connects += 1
                self.state.last_error = None
                backoff = 5
                self._notify()
                await self.request_config()
                ping_task = asyncio.get_running_loop().create_task(self._ping_loop())
                await self._read_loop()
            except asyncio.CancelledError:
                raise
            except LoginRejected as err:
                self.state.last_error = str(err)
                self._err(str(err))
                _LOGGER.error("Ropam Neo: %s", err)
                # nie męczymy centrali złym kodem - ryzyko blokady
                backoff = 300
            except NeoError as err:
                self.state.last_error = str(err)
                self._err(str(err))
                _LOGGER.warning("Ropam Neo: %s", err)
            except (ProtocolError, OSError, asyncio.TimeoutError) as err:
                msg = f"{type(err).__name__}: {err}"
                self.state.last_error = msg
                self._err(msg)
                _LOGGER.warning("Ropam Neo: %s", msg)
            except Exception as err:  # noqa: BLE001
                msg = f"{type(err).__name__}: {err}"
                self.state.last_error = msg
                self._err(msg)
                _LOGGER.exception("Ropam Neo: nieoczekiwany błąd")
            finally:
                if ping_task is not None:
                    ping_task.cancel()
                await self._close()
            if self._stopping:
                break
            self._info(f"Ponowne łączenie za {backoff} s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120) if backoff < 300 else 300

    async def _ping_loop(self) -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            try:
                await self._send(T_PING, b"")
            except Exception as err:  # noqa: BLE001
                self._err(f"Ping nieudany: {err}")
                return

    async def _read_loop(self) -> None:
        crc_errors = 0
        while not self._stopping:
            try:
                frame = await self._recv_frame(IDLE_TIMEOUT)
            except BadFrameError:
                crc_errors += 1
                if crc_errors >= 5:
                    raise ProtocolError("Zbyt wiele błędnych ramek")
                continue
            except asyncio.TimeoutError as err:
                raise CannotConnect(
                    f"Brak danych z centrali przez {IDLE_TIMEOUT} s"
                ) from err
            crc_errors = 0
            self._handle_frame(frame)
            if frame.ftype == T_SILENT_CLOSE:
                raise CannotConnect("Centrala zamknęła sesję (SILENTCLOSE)")

    def _handle_frame(self, frame: Frame) -> None:
        ftype = frame.ftype
        if ftype == T_STATUS:
            text = frame.text()
            old = self.state.status.raw if self.state.status else None
            st = parse_status(text)
            self.state.status = st
            if text != old:
                self._add_log("RX", f"STATUS {text}")
                if st.parse_error:
                    self._err(f"Parser statusu: {st.parse_error}")
            if self.state.config is not None:
                self._ready.set()
            self._notify()
            return
        if ftype == T_CONFIG:
            text = frame.text()
            self.state.config_raw = text
            try:
                self.state.config = parse_config(text)
                self._add_log(
                    "RX",
                    "CONFIG "
                    + json.dumps(_mask_config(self.state.config), ensure_ascii=False),
                )
            except ProtocolError as err:
                self._add_log("RX", f"CONFIG (surowy, {len(text)} znaków)")
                self._err(str(err))
                self.state.config = {}
            if self.state.status is not None:
                self._ready.set()
            self._notify()
            return
        if ftype == T_EXT_STATUS:
            text = frame.text()
            if text != self.state.ext_status_raw:
                self._add_log("RX", f"EXTSTATUS {text}")
            self.state.ext_status_raw = text
            return
        if ftype == T_MESSAGE:
            mtype = frame.data[0] if frame.data else 0
            text = frame.text()[1:] if len(frame.data) > 1 else ""
            self._add_log("RX", f"MESSAGE typ={mtype} {text}")
            if text and mtype not in (90, 91, 92):
                self.state.last_message = text
                self.state.last_message_time = time.time()
                for cb in list(self._message_listeners):
                    try:
                        cb(text)
                    except Exception:  # noqa: BLE001
                        _LOGGER.exception("Błąd listenera komunikatu")
                self._notify()
            return
        if ftype == T_EVENTS:
            self._add_log("RX", f"EVENTS {frame.text()}")
            return
        if ftype in (T_PING, T_ACK):
            self._add_log("RX", f"{frame.name}({ftype})")
            return
        if ftype in (T_NACK, T_ARM, T_DISARM, T_SETOUTS, T_PANIC):
            self._add_log(
                "RX", f"{frame.name}({ftype}) {frame.data.hex(' ') if frame.data else ''}"
            )
            return
        self._add_log(
            "RX",
            f"{frame.name}({ftype}) len={len(frame.data)} "
            f"{frame.data[:64].hex(' ')}",
        )

    # ------------------------------------------------------------ diagnostics

    def diagnostics(self) -> dict[str, Any]:
        st = self.state
        return {
            "host": self.host,
            "port": self.port,
            "device_id": _mask(self.device_id),
            "tcp_key": "****",
            "user_code": "****",
            "connected": st.connected,
            "connects": st.connects,
            "last_frame": st.last_frame,
            "last_error": st.last_error,
            "last_message": st.last_message,
            "login": st.login.as_dict() if st.login else None,
            "status_raw": st.status.raw if st.status else None,
            "status": st.status.as_dict() if st.status else None,
            "ext_status_raw": st.ext_status_raw,
            "config": _mask_config(st.config),
            "log": [e.as_dict() for e in self.log],
        }


def _mask(value: str) -> str:
    if len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]


def _mask_config(cfg: dict[str, Any] | None) -> dict[str, Any] | None:
    if cfg is None:
        return None
    out = dict(cfg)
    for key in ("deviceID", "phone"):
        if out.get(key):
            out[key] = _mask(str(out[key]))
    return out
