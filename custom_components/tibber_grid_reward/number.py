"""Platform for number integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number platform."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    api = entry_data["api"]
    flex_devices = entry_data["flex_devices"]

    entities = []
    for device in flex_devices:
        if device["type"] == "vehicle":
            vehicle_id = device["id"]
            entity = BatteryLevelEntity(api, config_entry.entry_id, device)
            entities.append(entity)
            hass.data[DOMAIN][config_entry.entry_id]["vehicle_devices"][vehicle_id].append(entity)

    async_add_entities(entities)


class BatteryLevelEntity(NumberEntity):
    """Representation of an assumed/manual battery level for an offline vehicle.

    This is only meaningful for "offline" vehicles (tracked manually, not
    directly API-connected, e.g. Nissan Leaf, Renault 5 E-TECH) — the
    write key (offline.vehicle.batteryLevel) was confirmed against one such
    vehicle. "Online" vehicles (e.g. Tesla) report real telemetry via
    battery.level instead, so this entity is created for every vehicle
    (mirroring DepartureTimeEntity), but stays unavailable until the first
    incoming vehicleState update confirms the vehicle is offline. It is
    never populated or writable for a vehicle confirmed online.
    """

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, api, entry_id, device):
        """Initialize the number entity."""
        self._api = api
        self._entry_id = entry_id
        self._home_id = api.home_id
        self._device_id = device["id"]
        self._device_name = device.get("name", self._device_id)
        self._attr_name = f"{self._device_name} Battery Level"
        self._attr_unique_id = f"{self._device_id}_battery_level"
        self._attr_native_value = None
        # Unknown until the first vehicleState update reports isAlive.
        # Stay unavailable until we've confirmed this vehicle is offline —
        # see the class docstring for why online vehicles are excluded.
        self._attr_available = False

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }

    @callback
    def update_data(self, data: dict[str, Any]) -> None:
        """Update the entity."""
        is_alive = data.get("isAlive")

        if is_alive is False:
            # Confirmed offline vehicle: this entity applies.
            self._attr_available = True
            battery = data.get("battery") or {}
            level = battery.get("level")
            self._attr_native_value = level if isinstance(level, (int, float)) else None
        else:
            # Online, or kind not yet known from this payload: stay
            # unavailable rather than show/allow editing a value that
            # isn't confirmed meaningful for this vehicle.
            if self._attr_available:
                _LOGGER.debug(
                    "%s reported isAlive=%s; marking battery level unavailable",
                    self.entity_id,
                    is_alive,
                )
            self._attr_available = False
            self._attr_native_value = None

        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Set the battery level."""
        if not self._attr_available:
            _LOGGER.warning(
                "Ignoring battery level change for %s: vehicle is not confirmed offline",
                self.entity_id,
            )
            return

        _LOGGER.debug("Setting battery level to %s for %s", value, self.entity_id)
        await self._api.set_battery_level(
            home_id=self._home_id,
            vehicle_id=self._device_id,
            level=int(value),
        )
        self._attr_native_value = value
        self.async_write_ha_state()
