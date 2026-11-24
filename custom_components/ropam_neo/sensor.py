"""Temperatury, wejście analogowe, napięcie, wilgotność, komunikaty."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import RopamNeoClient
from .entity import RopamEntity, config_names, pick_name


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    client: RopamNeoClient = entry.runtime_data
    st = client.state.status
    entities: list[SensorEntity] = [RopamLastMessage(entry, client)]
    if st is not None:
        t_names = config_names(client, "temps")
        for i, err in enumerate(st.temp_errors):
            if err == "none":
                continue
            entities.append(
                RopamTemperature(
                    entry, client, i, pick_name(t_names, i, f"Temperatura {i + 1}")
                )
            )
        if st.analog_unit is not None:
            cfg = client.state.config or {}
            name = str(cfg.get("analog") or "").strip() or "Wejście analogowe AI"
            entities.append(RopamAnalog(entry, client, name))
        if st.supply_voltage is not None:
            entities.append(RopamVoltage(entry, client))
        h_names = config_names(client, "wiredsens")
        for i, hum in enumerate(st.humidity):
            if hum is None:
                continue
            entities.append(
                RopamHumidity(
                    entry, client, i, pick_name(h_names, i, f"Wilgotność {i + 1}")
                )
            )
    async_add_entities(entities)


class RopamTemperature(RopamEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, entry, client, idx: int, name: str) -> None:
        super().__init__(entry, client, f"temperature_{idx + 1}")
        self._idx = idx
        self._attr_name = name

    @property
    def native_value(self) -> float | None:
        st = self.status
        if st is None or self._idx >= len(st.temperatures):
            return None
        return st.temperatures[self._idx]


class RopamAnalog(RopamEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:sine-wave"

    def __init__(self, entry, client, name: str) -> None:
        super().__init__(entry, client, "analog_1")
        self._attr_name = name

    @property
    def native_value(self) -> float | None:
        st = self.status
        return st.analog_value if st else None

    @property
    def native_unit_of_measurement(self) -> str | None:
        st = self.status
        unit = st.analog_unit if st else None
        return unit or None


class RopamVoltage(RopamEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Napięcie zasilania"

    def __init__(self, entry, client) -> None:
        super().__init__(entry, client, "supply_voltage")

    @property
    def native_value(self) -> float | None:
        st = self.status
        return st.supply_voltage if st else None


class RopamHumidity(RopamEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, entry, client, idx: int, name: str) -> None:
        super().__init__(entry, client, f"humidity_{idx + 1}")
        self._idx = idx
        self._attr_name = name

    @property
    def native_value(self) -> int | None:
        st = self.status
        if st is None or self._idx >= len(st.humidity):
            return None
        return st.humidity[self._idx]


class RopamLastMessage(RopamEntity, SensorEntity):
    _attr_name = "Ostatni komunikat"
    _attr_icon = "mdi:message-alert-outline"

    def __init__(self, entry, client) -> None:
        super().__init__(entry, client, "last_message")

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str | None:
        msg = self._client.state.last_message
        return msg[:255] if msg else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        ts = self._client.state.last_message_time
        if ts is None:
            return None
        return {"czas": datetime.fromtimestamp(ts, timezone.utc).isoformat()}
