"""Pobieranie diagnostyki (karta integracji → Pobierz diagnostykę)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_ID, CONF_TCP_KEY, CONF_USER_CODE, VERSION
from .panel import clients

TO_REDACT = {CONF_DEVICE_ID, CONF_TCP_KEY, CONF_USER_CODE}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    client = clients(hass).get(entry.entry_id)
    return {
        "version": VERSION,
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "client": client.diagnostics() if client else None,
    }
