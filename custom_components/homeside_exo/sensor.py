"""Sensor-plattform för HomeSide EXO."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import base_id, sensor_points
from .const import DOMAIN
from .coordinator import ExoCoordinator

# unit i points.json -> (device_class, HA-enhet, state_class)
_NUMERIC_UNITS = {
    "°C": (SensorDeviceClass.TEMPERATURE, "°C", SensorStateClass.MEASUREMENT),
    "Bar": (SensorDeviceClass.PRESSURE, "bar", SensorStateClass.MEASUREMENT),
    "dB": (None, "dB", SensorStateClass.MEASUREMENT),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Skapa sensorentiteter ur punktdefinitionen."""
    store = hass.data[DOMAIN][entry.entry_id]
    coordinator: ExoCoordinator = store["coordinator"]
    uid_base = base_id(entry)
    device = DeviceInfo(
        identifiers={(DOMAIN, uid_base)},
        name="Fjärrvärmecentral",
        manufacturer="Regin",
        model="HomeSide / ControllerWeb",
    )
    async_add_entities(
        ExoSensor(coordinator, uid_base, device, int(idx), meta)
        for idx, meta in sensor_points(store["points"]).items()
    )


class ExoSensor(CoordinatorEntity[ExoCoordinator], SensorEntity):
    """En datapunkt från regulatorn."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: ExoCoordinator,
        uid_base: str,
        device: DeviceInfo,
        idx: int,
        meta: dict,
    ) -> None:
        super().__init__(coordinator)
        self._idx = idx
        self._values: dict | None = meta.get("values")
        self._attr_unique_id = f"{uid_base}_{idx}"
        self._attr_name = meta.get("label", f"Punkt {idx}")
        self._attr_entity_registry_enabled_default = meta.get("enabled", True)
        self._attr_device_info = device

        if self._values or meta.get("type") == "String":
            # Textvärde (ventillägen, på/av, status, version) – ren textsensor.
            self._attr_native_unit_of_measurement = None
        else:
            dev_class, unit, state_class = _NUMERIC_UNITS.get(
                meta.get("unit", ""), (None, meta.get("unit") or None, None)
            )
            self._attr_device_class = dev_class
            self._attr_native_unit_of_measurement = unit
            self._attr_state_class = state_class

        # Mottagning/signalstyrka och versionsinfo hör hemma som diagnostik.
        if meta.get("unit") == "dB" or meta.get("category") == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def _read(self) -> tuple[object, object]:
        data = self.coordinator.data or {}
        return data.get(self._idx, (None, "saknas"))

    @property
    def available(self) -> bool:
        _val, err = self._read()
        return super().available and err is None

    @property
    def native_value(self):
        val, err = self._read()
        if err is not None:
            return None
        if self._values:
            return self._values.get(str(val), str(val))
        return val
