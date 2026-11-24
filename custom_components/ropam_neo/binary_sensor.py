"""Czujki (wejścia), wyjścia tylko do odczytu i stany techniczne."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import RopamNeoClient
from .entity import RopamEntity, config_names, pick_name
from .protocol import (
    INPUT_ACTIVE,
    INPUT_STATES,
    OUTPUT_CONTROLLABLE,
    OUTPUT_ON,
    OUTPUT_STATES,
)

_CLASS_HINTS: list[tuple[tuple[str, ...], BinarySensorDeviceClass]] = [
    (("dym", "pożar", "pozar", "smoke"), BinarySensorDeviceClass.SMOKE),
    (("zalan", "woda", "wyciek", "flood"), BinarySensorDeviceClass.MOISTURE),
    (("gaz", "co2", "czad"), BinarySensorDeviceClass.GAS),
    (("okno", "okna", "window"), BinarySensorDeviceClass.WINDOW),
    (("drzwi", "furtk", "door"), BinarySensorDeviceClass.DOOR),
    (("brama", "garaż", "garaz", "kontaktron", "gate"), BinarySensorDeviceClass.OPENING),
    (("sabotaż", "sabotaz", "tamper"), BinarySensorDeviceClass.TAMPER),
    (("pir", "ruch", "czujka", "motion"), BinarySensorDeviceClass.MOTION),
]


def _guess_class(name: str) -> BinarySensorDeviceClass | None:
    low = name.lower()
    for keys, cls in _CLASS_HINTS:
        if any(k in low for k in keys):
            return cls
    return None


def input_indexes(client: RopamNeoClient) -> list[int]:
    st = client.state.status
    if st is None:
        return []
    names = config_names(client, "inputs")
    out = []
    for i, ch in enumerate(st.inputs):
        if ch not in INPUT_STATES:
            continue
        has_name = i < len(names) and bool(names[i])
        if ch == "X" and not has_name:
            continue
        out.append(i)
    return out


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    client: RopamNeoClient = entry.runtime_data
    st = client.state.status
    entities: list[BinarySensorEntity] = []

    in_names = config_names(client, "inputs")
    for i in input_indexes(client):
        entities.append(
            RopamInput(entry, client, i, pick_name(in_names, i, f"Wejście {i + 1}"))
        )

    out_names = config_names(client, "outputs")
    if st is not None:
        for i, ch in enumerate(st.outputs):
            if ch in OUTPUT_STATES and ch not in OUTPUT_CONTROLLABLE:
                entities.append(
                    RopamOutputState(
                        entry, client, i, pick_name(out_names, i, f"Wyjście {i + 1}")
                    )
                )
        zone_names = config_names(client, "zones")
        for z in range(len(st.zones)):
            entities.append(
                RopamZoneTamper(
                    entry, client, z, pick_name(zone_names, z, f"Strefa {z + 1}")
                )
            )
        if st.ac_ok is not None:
            entities.append(RopamAcPower(entry, client))
    entities.append(RopamConnection(entry, client))
    async_add_entities(entities)


class RopamInput(RopamEntity, BinarySensorEntity):
    def __init__(self, entry, client, idx: int, name: str) -> None:
        super().__init__(entry, client, f"input_{idx + 1}")
        self._idx = idx
        self._attr_name = name
        self._attr_device_class = _guess_class(name)

    @property
    def _char(self) -> str:
        st = self.status
        return st.input_char(self._idx) if st else "-"

    @property
    def is_on(self) -> bool | None:
        ch = self._char
        if ch not in INPUT_STATES:
            return None
        return ch in INPUT_ACTIVE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ch = self._char
        return {
            "numer": self._idx + 1,
            "stan": INPUT_STATES.get(ch, "brak"),
            "znak": ch,
            "sabotaz": ch == "!",
            "pamiec_alarmu": ch in ("a", "A"),
            "slaba_bateria": ch in ("w", "W"),
            "zablokowane": ch in ("b", "B"),
            "awaria": ch in ("f", "F", "?"),
        }


class RopamOutputState(RopamEntity, BinarySensorEntity):
    """Wyjście bez prawa sterowania z aplikacji - tylko stan."""

    def __init__(self, entry, client, idx: int, name: str) -> None:
        super().__init__(entry, client, f"output_state_{idx + 1}")
        self._idx = idx
        self._attr_name = name
        self._attr_icon = "mdi:electric-switch"

    @property
    def is_on(self) -> bool | None:
        st = self.status
        if st is None:
            return None
        ch = st.output_char(self._idx)
        if ch not in OUTPUT_STATES:
            return None
        return ch in OUTPUT_ON

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        st = self.status
        ch = st.output_char(self._idx) if st else "-"
        return {"numer": self._idx + 1, "stan": OUTPUT_STATES.get(ch, "brak"), "znak": ch}


class RopamZoneTamper(RopamEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.TAMPER
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry, client, idx: int, zone_name: str) -> None:
        super().__init__(entry, client, f"zone_{idx + 1}_tamper")
        self._idx = idx
        self._attr_name = f"{zone_name} sabotaż"

    @property
    def is_on(self) -> bool | None:
        st = self.status
        if st is None or self._idx >= len(st.zones):
            return None
        return st.zones[self._idx].tamper


class RopamAcPower(RopamEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.POWER
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Zasilanie 230V"

    def __init__(self, entry, client) -> None:
        super().__init__(entry, client, "ac_power")

    @property
    def is_on(self) -> bool | None:
        st = self.status
        return st.ac_ok if st else None


class RopamConnection(RopamEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Połączenie"

    def __init__(self, entry, client) -> None:
        super().__init__(entry, client, "connection")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self._client.connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        st = self._client.state
        return {
            "ostatni_blad": st.last_error,
            "polaczen": st.connects,
            "ostatnia_ramka": st.last_frame,
        }
