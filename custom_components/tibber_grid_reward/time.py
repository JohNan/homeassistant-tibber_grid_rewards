"""Platform for time integration."""
from __future__ import annotations

import datetime
import logging
from typing import Any

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the time platform."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    api = entry_data["api"]
    flex_devices = entry_data["flex_devices"]

    entities = []
    for device in flex_devices:
        if device["type"] == "vehicle":
            vehicle_id = device["id"]
            for day in range(7):
                entity = DepartureTimeEntity(api, config_entry.entry_id, device, day)
                entities.append(entity)
                hass.data[DOMAIN][config_entry.entry_id]["vehicle_devices"][vehicle_id].append(entity)
    
    async_add_entities(entities)


class DepartureTimeEntity(TimeEntity):
    """Representation of a departure time entity."""

    def __init__(self, api, entry_id, device, day_index):
        """Initialize the time entity."""
        self._api = api
        self._entry_id = entry_id
        self._home_id = api.home_id
        self._device_id = device["id"]
        self._device_name = device.get("name", self._device_id)
        self._day_index = day_index
        self._day_name = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][day_index]
        self._attr_name = f"{self._device_name} Departure Time {self._day_name.capitalize()}"
        self._attr_unique_id = f"{self._device_id}_departure_time_{self._day_name}"
        self._attr_native_value = None

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }

    @callback
    def update_data(self, data: dict[str, Any]) -> None:
        """Update the entity."""
        settings = data.get("userSettings", [])
        key = f"online.vehicle.smartCharging.departureTimes.{self._day_name}"
        time_str = None
        for setting in settings:
            if setting["key"] == key:
                time_str = setting["value"]
                break
        
        if time_str:
            try:
                self._attr_native_value = datetime.time.fromisoformat(time_str)
            except (ValueError, TypeError):
                self._attr_native_value = None
        else:
            self._attr_native_value = None
            
        self.async_write_ha_state()

    async def async_set_value(self, value: datetime.time | None) -> None:
        """Set the departure time."""
        _LOGGER.debug("Setting departure time to %s for %s", value, self.entity_id)
        
        if value == datetime.time(0, 0):
            time_str = None
        else:
            time_str = value.strftime("%H:%M") if value else None
            
        await self._api.set_departure_time(
            home_id=self._home_id,
            vehicle_id=self._device_id,
            day=self._day_name,
            time_str=time_str,
        )
        self._attr_native_value = value
        self.async_write_ha_state()