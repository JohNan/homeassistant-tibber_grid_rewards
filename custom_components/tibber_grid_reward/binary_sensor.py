"""Platform for binary sensor integration."""
from __future__ import annotations
from typing import Any
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Set up the binary sensor platform."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    api = entry_data["api"]

    sensor = GridRewardActiveSensor(api, config_entry.entry_id)
    
    entry_data["grid_reward_devices"].append(sensor)
    async_add_entities([sensor])


class GridRewardActiveSensor(BinarySensorEntity):
    """Representation of a Grid Reward Active Sensor."""

    _attr_device_class = BinarySensorDeviceClass.POWER

    def __init__(self, api, entry_id):
        """Initialize the binary sensor."""
        self._api = api
        self._entry_id = entry_id
        self._attributes = {}
        self._attr_is_on = False
        self._attr_name = "Grid Reward Active"
        self._attr_unique_id = f"{self._entry_id}_grid_reward_active"

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "Tibber Grid Reward",
            "manufacturer": "Tibber",
        }

    @callback
    def update_data(self, data: dict[str, Any]) -> None:
        """Update the entity."""
        _LOGGER.debug("Updating binary sensor with data: %s", data)
        self._attributes = data
        self._attr_is_on = (
            self._attributes.get("state", {}).get("__typename") == "GridRewardDelivering"
        )
        self.async_write_ha_state()