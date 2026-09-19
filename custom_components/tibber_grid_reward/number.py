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
    """Set up the number platform.

    A vehicle's online/offline kind isn't known yet at this point — it only
    arrives later via the first vehicleState subscription update. So rather
    than creating a BatteryLevelEntity for every vehicle up front, a
    lightweight manager is registered for each one; it decides whether the
    entity should exist at all once that first update arrives. See
    _BatteryLevelEntityManager.
    """
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    api = entry_data["api"]
    flex_devices = entry_data["flex_devices"]

    for device in flex_devices:
        if device["type"] == "vehicle":
            vehicle_id = device["id"]
            vehicle_devices = entry_data["vehicle_devices"][vehicle_id]
            manager = _BatteryLevelEntityManager(api, config_entry.entry_id, device, vehicle_devices, async_add_entities)
            vehicle_devices.append(manager)


class _BatteryLevelEntityManager:
    """Decides, from the first vehicleState update, whether a
    BatteryLevelEntity should be created for this vehicle at all.

    Confirmed live (2026-08-18): battery.level is meaningless (null) for
    online vehicles (e.g. Tesla) — there's nothing to show or let a user
    set. So the entity is only created once a vehicle's first update
    confirms isAlive is False. Online vehicles never get one, rather than
    getting one that would sit permanently unavailable.

    Lives in the same `vehicle_devices` dispatch list as real entities
    (time.py's DepartureTimeEntity, and — once resolved offline — its own
    BatteryLevelEntity) so it receives updates through the existing
    per-vehicle callback without any change to that dispatch mechanism.
    Removes itself from the list once resolved either way.

    Note: this does not clean up a battery level entity a previous version
    of this integration may have already registered for a vehicle that's
    now confirmed online — that's left in the entity registry showing
    unavailable until manually removed (Settings > Devices & Services >
    Entities).
    """

    def __init__(self, api, entry_id, device, vehicle_devices, async_add_entities):
        self._api = api
        self._entry_id = entry_id
        self._device = device
        self._vehicle_devices = vehicle_devices
        self._async_add_entities = async_add_entities
        self._resolved = False

    @callback
    def update_data(self, data: dict[str, Any]) -> None:
        """Resolve, at most once, whether this vehicle gets the entity."""
        if self._resolved:
            return

        is_alive = data.get("isAlive")
        if is_alive is None:
            # Kind not yet known from this payload; wait for a later one.
            return

        self._resolved = True
        if self in self._vehicle_devices:
            self._vehicle_devices.remove(self)

        if is_alive is False:
            _LOGGER.debug(
                "Vehicle %s confirmed offline; adding its battery level entity",
                self._device["id"],
            )
            entity = BatteryLevelEntity(self._api, self._entry_id, self._device, data)
            self._vehicle_devices.append(entity)
            self._async_add_entities([entity])
        else:
            _LOGGER.debug(
                "Vehicle %s confirmed online; battery level entity is not applicable",
                self._device["id"],
            )


class BatteryLevelEntity(NumberEntity):
    """Representation of an assumed/manual battery level for an offline vehicle.

    Only ever created by _BatteryLevelEntityManager once a vehicle's first
    update has confirmed isAlive is False, so it applies for as long as it
    exists. The write key (offline.vehicle.batteryLevel) was confirmed
    against one such vehicle via a live write-then-readback test.
    """

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, api, entry_id, device, data: dict[str, Any]):
        """Initialize the number entity, populated from the data that confirmed it."""
        self._api = api
        self._entry_id = entry_id
        self._home_id = api.home_id
        self._device_id = device["id"]
        self._device_name = device.get("name", self._device_id)
        self._attr_name = f"{self._device_name} Battery Level"
        self._attr_unique_id = f"{self._device_id}_battery_level"
        self._attr_available = True
        self._apply_data(data)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }

    def _apply_data(self, data: dict[str, Any]) -> None:
        """Parse battery.level out of an update, handling it being absent."""
        battery = data.get("battery") or {}
        level = battery.get("level")
        self._attr_native_value = level if isinstance(level, (int, float)) else None

    @callback
    def update_data(self, data: dict[str, Any]) -> None:
        """Update the entity."""
        if self.hass is None:
            # async_add_entities() (called by the manager that created us)
            # registers this entity with hass as a background task rather
            # than synchronously, so a vehicleState update can land here
            # before that finishes. __init__ already applied the data that
            # triggered creation; skip until we're actually attached, the
            # next update will catch up.
            _LOGGER.debug(
                "Skipping battery level update for vehicle %s: not yet attached to hass",
                self._device_id,
            )
            return

        if data.get("isAlive") is True:
            # Defensive: this entity is only ever created for a vehicle
            # confirmed offline, but if a later update reports it online
            # there's nothing meaningful left to show (see class docstring).
            if self._attr_available:
                _LOGGER.debug(
                    "%s reported isAlive=True after being created for an "
                    "offline vehicle; marking battery level unavailable",
                    self.entity_id,
                )
            self._attr_available = False
            self._attr_native_value = None
        else:
            self._attr_available = True
            self._apply_data(data)

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
