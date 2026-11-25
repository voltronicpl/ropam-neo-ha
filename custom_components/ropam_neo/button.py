"""Przycisk alarmu napadowego (PANIC)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import RopamNeoClient
from .const import CONF_PANIC_BUTTON
from .entity import RopamEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if not entry.options.get(CONF_PANIC_BUTTON, True):
        return
    client: RopamNeoClient = entry.runtime_data
    async_add_entities([RopamPanicButton(entry, client)])


class RopamPanicButton(RopamEntity, ButtonEntity):
    _attr_name = "Alarm napadowy"
    _attr_icon = "mdi:alarm-light"

    def __init__(self, entry: ConfigEntry, client: RopamNeoClient) -> None:
        super().__init__(entry, client, "panic")

    async def async_press(self) -> None:
        await self._command(self._client.panic())
