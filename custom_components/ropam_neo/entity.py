"""Wspólna baza encji Ropam Neo."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .client import NeoError, RopamNeoClient
from .const import DOMAIN, MANUFACTURER
from .protocol import NeoStatus

HW_MODELS = {"7": "Neo-IP / NeoLTE-IP"}


def device_key(entry: ConfigEntry) -> str:
    return entry.unique_id or entry.entry_id


def config_names(client: RopamNeoClient, key: str) -> list[str]:
    cfg = client.state.config or {}
    val = cfg.get(key)
    if isinstance(val, str):
        val = val.split("\n")
    if not isinstance(val, list):
        return []
    return [str(v).strip() if v is not None else "" for v in val]


def pick_name(names: list[str], idx: int, fallback: str) -> str:
    if idx < len(names) and names[idx]:
        return names[idx]
    return fallback


class RopamEntity(Entity):
    """Encja zasilana stanem klienta (push)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, client: RopamNeoClient, key: str) -> None:
        self._client = client
        self._attr_unique_id = f"{device_key(entry)}_{key}"
        st = client.state.status
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_key(entry))},
            name="Centrala Ropam",
            manufacturer=MANUFACTURER,
            model=HW_MODELS.get(st.hardware if st else "", "Neo-IP"),
            sw_version=st.firmware if st else None,
        )

    @property
    def status(self) -> NeoStatus | None:
        return self._client.state.status

    @property
    def available(self) -> bool:
        return self._client.connected and self._client.state.status is not None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._client.add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    async def _command(self, coro) -> None:
        try:
            await coro
        except NeoError as err:
            raise HomeAssistantError(f"Ropam Neo: {err}") from err
        except OSError as err:
            raise HomeAssistantError(f"Ropam Neo: błąd połączenia: {err}") from err
