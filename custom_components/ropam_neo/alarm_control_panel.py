"""Strefy alarmowe Ropam Neo."""

from __future__ import annotations

from typing import Any

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import RopamNeoClient
from .entity import RopamEntity, config_names, pick_name


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    client: RopamNeoClient = entry.runtime_data
    st = client.state.status
    count = len(st.zones) if st and st.zones else 2
    names = config_names(client, "zones")
    async_add_entities(
        RopamZone(entry, client, i, pick_name(names, i, f"Strefa {i + 1}"))
        for i in range(count)
    )


class RopamZone(RopamEntity, AlarmControlPanelEntity):
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_AWAY
        | AlarmControlPanelEntityFeature.ARM_NIGHT
    )
    _attr_code_arm_required = False
    _attr_code_format = None

    def __init__(
        self, entry: ConfigEntry, client: RopamNeoClient, idx: int, name: str
    ) -> None:
        super().__init__(entry, client, f"zone_{idx + 1}")
        self._idx = idx
        self._attr_name = name

    @property
    def _zone(self):
        st = self.status
        if st is None or self._idx >= len(st.zones):
            return None
        return st.zones[self._idx]

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        z = self._zone
        if z is None:
            return None
        if z.alarm:
            return AlarmControlPanelState.TRIGGERED
        if z.entry_delay:
            return AlarmControlPanelState.PENDING
        if z.exit_delay:
            return AlarmControlPanelState.ARMING
        if z.night:
            return AlarmControlPanelState.ARMED_NIGHT
        if z.armed:
            return AlarmControlPanelState.ARMED_AWAY
        return AlarmControlPanelState.DISARMED

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        z = self._zone
        if z is None:
            return None
        login = self._client.state.login
        allowed = None
        if login is not None:
            allowed = login.zone1 if self._idx == 0 else login.zone2
        return {
            "gotowa": z.ready,
            "sabotaz": z.tamper,
            "czas_na_wyjscie": z.exit_delay,
            "czas_na_wejscie": z.entry_delay,
            "licznik": z.timer,
            "uprawnienia_uzytkownika": allowed,
            "surowy_bajt": z.raw,
        }

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        await self._command(self._client.arm(1 << self._idx, night=False))

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        await self._command(self._client.arm(1 << self._idx, night=True))

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        await self._command(self._client.disarm(1 << self._idx))
