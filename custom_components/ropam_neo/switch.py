"""Wyjścia centrali sterowane z HA."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import RopamNeoClient
from .entity import RopamEntity, config_names, pick_name
from .protocol import OUTPUT_CONTROLLABLE, OUTPUT_ON, OUTPUT_STATES


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    client: RopamNeoClient = entry.runtime_data
    st = client.state.status
    if st is None:
        return
    names = config_names(client, "outputs")
    async_add_entities(
        RopamOutput(entry, client, i, pick_name(names, i, f"Wyjście {i + 1}"))
        for i, ch in enumerate(st.outputs)
        if ch in OUTPUT_CONTROLLABLE
    )


class RopamOutput(RopamEntity, SwitchEntity):
    def __init__(self, entry, client, idx: int, name: str) -> None:
        super().__init__(entry, client, f"output_{idx + 1}")
        self._idx = idx
        self._attr_name = name
        self._attr_icon = "mdi:electric-switch"

    @property
    def _char(self) -> str:
        st = self.status
        return st.output_char(self._idx) if st else "-"

    @property
    def is_on(self) -> bool | None:
        ch = self._char
        if ch not in OUTPUT_STATES:
            return None
        return ch in OUTPUT_ON

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ch = self._char
        return {
            "numer": self._idx + 1,
            "stan": OUTPUT_STATES.get(ch, "brak"),
            "znak": ch,
            "awaria": ch in ("F", "f"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._command(self._client.set_output(self._idx, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._command(self._client.set_output(self._idx, False))
