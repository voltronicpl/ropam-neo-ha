"""Zakładka diagnostyki w menu bocznym + API websocket."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback

from .client import RopamNeoClient
from .const import (
    DOMAIN,
    PANEL_ELEMENT,
    PANEL_JS,
    PANEL_STATIC_URL,
    PANEL_URL_PATH,
    VERSION,
)

_FRONTEND_DIR = Path(__file__).parent / "frontend"


def _data(hass: HomeAssistant) -> dict[str, Any]:
    return hass.data.setdefault(DOMAIN, {})


def clients(hass: HomeAssistant) -> dict[str, RopamNeoClient]:
    return _data(hass).setdefault("clients", {})


async def async_register_panel(hass: HomeAssistant) -> None:
    data = _data(hass)
    if not data.get("static_registered"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(PANEL_STATIC_URL, str(_FRONTEND_DIR), False)]
        )
        data["static_registered"] = True
    if not data.get("ws_registered"):
        websocket_api.async_register_command(hass, ws_diagnostics)
        websocket_api.async_register_command(hass, ws_clear_log)
        websocket_api.async_register_command(hass, ws_reconnect)
        data["ws_registered"] = True
    if data.get("panel_registered"):
        return
    try:
        mtime = int((_FRONTEND_DIR / PANEL_JS).stat().st_mtime)
    except OSError:
        mtime = 0
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title="Ropam Neo",
        sidebar_icon="mdi:shield-home-outline",
        frontend_url_path=PANEL_URL_PATH,
        require_admin=True,
        config={
            "_panel_custom": {
                "name": PANEL_ELEMENT,
                "module_url": f"{PANEL_STATIC_URL}/{PANEL_JS}?v={VERSION}-{mtime}",
                "embed_iframe": False,
                "trust_external": False,
            }
        },
    )
    data["panel_registered"] = True


@callback
def async_unregister_panel(hass: HomeAssistant) -> None:
    data = _data(hass)
    if data.get("panel_registered"):
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
        data["panel_registered"] = False


@websocket_api.websocket_command({vol.Required("type"): "ropam_neo/diagnostics"})
@websocket_api.require_admin
@callback
def ws_diagnostics(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    out = []
    regs = clients(hass)
    for entry in hass.config_entries.async_entries(DOMAIN):
        item: dict[str, Any] = {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "entry_state": entry.state.value,
        }
        client = regs.get(entry.entry_id)
        if client is not None:
            item.update(client.diagnostics())
        out.append(item)
    connection.send_result(msg["id"], {"version": VERSION, "entries": out})


@websocket_api.websocket_command(
    {vol.Required("type"): "ropam_neo/clear_log", vol.Required("entry_id"): str}
)
@websocket_api.require_admin
@callback
def ws_clear_log(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    client = clients(hass).get(msg["entry_id"])
    if client is not None:
        client.clear_log()
    connection.send_result(msg["id"], {"ok": client is not None})


@websocket_api.websocket_command(
    {vol.Required("type"): "ropam_neo/reload", vol.Required("entry_id"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_reconnect(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "Brak wpisu integracji")
        return
    hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))
    connection.send_result(msg["id"], {"ok": True})
