"""Platform for binary sensor integration."""
from __future__ import annotations
from typing import Any
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


GRID_REWARD_ACTIVE_SENSOR_DESCRIPTION = BinarySensorEntityDescription(
    key="grid_reward_active",
    name="Grid Reward Active",
    device_class=BinarySensorDeviceClass.POWER,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    api = entry_data["api"]

    sensor = GridRewardActiveSensor(
        api, config_entry.entry_id, GRID_REWARD_ACTIVE_SENSOR_DESCRIPTION
    )

    entry_data["grid_reward_devices"].append(sensor)
    async_add_entities([sensor])


class GridRewardActiveSensor(BinarySensorEntity):
    """Representation of a Grid Reward Active Sensor."""

    entity_description: BinarySensorEntityDescription

    def __init__(self, api, entry_id, description: BinarySensorEntityDescription):
        """Initialize the binary sensor."""
        self.entity_description = description
        self._api = api
        self._entry_id = entry_id
        self._attributes = {}
        self._attr_is_on = False
        self._attr_unique_id = f"{self._entry_id}_{self.entity_description.key}"

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
            self._attributes.get("state", {}).get("__typename")
            == "GridRewardDelivering"
        )
        self.async_write_ha_state()
