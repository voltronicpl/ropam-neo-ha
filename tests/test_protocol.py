import asyncio, os, sys
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
import sim_central as S
from ropam_neo import protocol as P
from ropam_neo.client import RopamNeoClient, LoginRejected, BadTcpKey, CannotConnect


def test_crc_and_frame_roundtrip():
    raw = P.encode_frame(3, P.T_STATUS, b"hello", b"k" * 16, P.DEFAULT_VECTOR)
    f = P.decode_frame(raw, b"k" * 16, P.DEFAULT_VECTOR)
    assert f.crc_ok and f.ftype == P.T_STATUS and f.data == b"hello"
    bad = P.decode_frame(raw, b"z" * 16, P.DEFAULT_VECTOR)
    assert not bad.crc_ok


def test_status_parse():
    st = P.parse_status(S.Central().status_text())
    assert st.parse_error is None, st.parse_error
    assert st.inputs[:2] == "10" and st.zones[0].ready and not st.zones[0].armed
    assert st.temperatures[0] == 23.0 and st.temperatures[1] is None
    assert st.supply_voltage == 13.8 and st.ac_ok and st.analog_value == 12.5 and st.analog_unit == "V"
    assert st.humidity == [None, None]


async def _run(code=S.CODE, key=S.TCP_KEY):
    c = S.Central()
    server = await asyncio.start_server(lambda r, w: S.handle(r, w, c), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return c, server, port


async def test_full_session(socket_enabled):
    if True:
        c, server, port = await _run()
        cl = RopamNeoClient("127.0.0.1", port, S.DEVICE_ID, S.TCP_KEY, S.CODE)
        info = await cl.async_test()
        assert info.user_no == 2 and info.zone1 and info.zone2 and info.remote
        cl.start()
        assert await cl.wait_ready(5)
        assert cl.state.config["zones"][1] == "Garaż"
        await cl.arm(0b01, night=True)
        await asyncio.sleep(0.3)
        assert cl.state.status.zones[0].armed and cl.state.status.zones[0].night
        await cl.disarm(0b01)
        await cl.set_output(0, True)
        await asyncio.sleep(0.3)
        assert not cl.state.status.zones[0].armed
        assert cl.state.status.outputs[0] == "1"
        arm = [d for t, d in c.received if t == P.T_ARM][0]
        assert arm == bytes([1, 1]) + b"1234"
        so = [d for t, d in c.received if t == P.T_SETOUTS][0]
        assert so == b"1" + b"x" * 31
        await cl.panic()
        await asyncio.sleep(0.3)
        assert any(t == P.T_PANIC for t, _ in c.received)
        assert cl.state.status.zones[0].alarm
        d = cl.diagnostics()
        txt = str(d)
        assert S.TCP_KEY not in txt and S.DEVICE_ID not in txt and "+48000000000" not in txt
        await cl.stop()
        server.close()


async def test_bad_code_and_key(socket_enabled):
    if True:
        c, server, port = await _run()
        try:
            await RopamNeoClient("127.0.0.1", port, S.DEVICE_ID, S.TCP_KEY, "0000").async_test()
            assert False
        except LoginRejected as e:
            assert e.code == "invalid_auth"
        try:
            await RopamNeoClient("127.0.0.1", port, S.DEVICE_ID, "zlyklucz12345678", S.CODE).async_test(timeout=20)
            assert False
        except (BadTcpKey, CannotConnect) as e:
            print("zły klucz ->", type(e).__name__, e)
        server.close()
