import asyncio
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

import sim_central as S
from custom_components.ropam_neo.client import LoginInfo, LoginRejected
from custom_components.ropam_neo.const import (
    CONF_DEVICE_ID,
    CONF_TCP_KEY,
    CONF_USER_CODE,
    DOMAIN,
)

DATA = {
    CONF_HOST: "127.0.0.1",
    CONF_PORT: 9999,
    CONF_DEVICE_ID: S.DEVICE_ID,
    CONF_TCP_KEY: S.TCP_KEY,
    CONF_USER_CODE: S.CODE,
}


async def test_config_flow_ok(hass, no_frontend):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    with patch(
        "custom_components.ropam_neo.config_flow.RopamNeoClient.async_test",
        return_value=LoginInfo(user_no=1, zone1=True),
    ), patch("custom_components.ropam_neo.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], DATA
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TCP_KEY] == S.TCP_KEY
    assert result["result"].unique_id == S.DEVICE_ID


async def test_config_flow_bad_code(hass, no_frontend):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.ropam_neo.config_flow.RopamNeoClient.async_test",
        side_effect=LoginRejected(3),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], DATA
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_setup_with_simulator(hass, no_frontend, socket_enabled):
    central = S.Central()
    server = await asyncio.start_server(
        lambda r, w: S.handle(r, w, central), "127.0.0.1", 0
    )
    port = server.sockets[0].getsockname()[1]
    entry = MockConfigEntry(
        domain=DOMAIN, data={**DATA, CONF_PORT: port}, unique_id=S.DEVICE_ID
    )
    entry.add_to_hass(hass)
    with patch("custom_components.ropam_neo.async_register_panel"):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    states = {s.entity_id: s for s in hass.states.async_all()}
    zone = next(s for e, s in states.items() if e.startswith("alarm_control_panel."))
    assert zone.state == "disarmed"
    assert any(e.startswith("binary_sensor.") and "pir_salon" in e for e in states)
    switches = [e for e in states if e.startswith("switch.")]
    assert switches, states.keys()

    await hass.services.async_call(
        "alarm_control_panel", "alarm_arm_away", {"entity_id": zone.entity_id}, blocking=True
    )
    for _ in range(20):
        await asyncio.sleep(0.05)
        await hass.async_block_till_done()
        if hass.states.get(zone.entity_id).state == "armed_away":
            break
    assert hass.states.get(zone.entity_id).state == "armed_away"

    panic = next(e for e in states if e.startswith("button."))
    await hass.services.async_call("button", "press", {"entity_id": panic}, blocking=True)
    for _ in range(20):
        await asyncio.sleep(0.05)
        await hass.async_block_till_done()
        if hass.states.get(zone.entity_id).state == "triggered":
            break
    assert hass.states.get(zone.entity_id).state == "triggered"
    assert any(t == 42 for t, _ in central.received)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    server.close()


async def test_options_toggle_panic_without_reconnect(hass, no_frontend):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id=S.DEVICE_ID)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    with patch(
        "custom_components.ropam_neo.config_flow.RopamNeoClient.async_test"
    ) as test:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**DATA, "panic_button": False}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["panic_button"] is False
    test.assert_not_called()
