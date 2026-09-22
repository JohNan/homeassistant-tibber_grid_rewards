"""Platform for binary sensor integration."""

from __future__ import annotations

import logging
from typing import Any

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
    flex_devices = entry_data.get("flex_devices", [])

    sensors: list[BinarySensorEntity] = []

    # Home-level Grid Reward active binary sensor
    home_sensor = GridRewardActiveSensor(
        api, config_entry.entry_id, GRID_REWARD_ACTIVE_SENSOR_DESCRIPTION
    )
    sensors.append(home_sensor)
    entry_data["grid_reward_devices"].append(home_sensor)

    # Per-flex-device Grid Reward active binary sensors
    for device in flex_devices:
        flex_sensor = FlexDeviceGridRewardActiveSensor(
            api, config_entry.entry_id, device, GRID_REWARD_ACTIVE_SENSOR_DESCRIPTION
        )
        sensors.append(flex_sensor)
        entry_data["grid_reward_devices"].append(flex_sensor)

    async_add_entities(sensors)


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
        if self.hass is not None:
            self.async_write_ha_state()


class FlexDeviceGridRewardActiveSensor(BinarySensorEntity):
    """Representation of a per-flex-device Grid Reward Active Sensor."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        api: Any,
        entry_id: str,
        device: dict[str, Any],
        description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the flex device binary sensor."""
        self.entity_description = description
        self._api = api
        self._entry_id = entry_id
        self._device = device
        self._device_id = device["id"]
        self._device_type = device.get("type")
        self._device_name = device.get("name", self._device_id)
        self._attributes: dict[str, Any] = {}
        self._attr_is_on = False
        self._attr_unique_id = f"{self._device_id}_{self.entity_description.key}"
        self._attr_name = f"{self._device_name} {self.entity_description.name}"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": "Tibber",
            "via_device": (DOMAIN, self._entry_id),
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes for this flex device's grid reward state."""
        return self._attributes

    @callback
    def update_data(self, data: dict[str, Any]) -> None:
        """Update the entity with grid reward status data."""
        _LOGGER.debug(
            "Updating flex device binary sensor %s with data: %s",
            self.unique_id,
            data,
        )
        flex_devices = data.get("flexDevices", [])
        device_id_key = "vehicleId" if self._device_type == "vehicle" else "batteryId"
        for dev in flex_devices:
            dev_id = (
                dev.get(device_id_key) or dev.get("vehicleId") or dev.get("batteryId")
            )
            if dev_id == self._device_id:
                state_data = dev.get("state") or {}
                self._attr_is_on = (
                    state_data.get("__typename") == "GridRewardDelivering"
                )
                attrs: dict[str, Any] = {}
                if "__typename" in state_data:
                    attrs["state"] = state_data["__typename"]
                if "kind" in state_data and state_data["kind"] is not None:
                    attrs["kind"] = state_data["kind"]
                if "reason" in state_data and state_data["reason"] is not None:
                    attrs["reason"] = state_data["reason"]
                if "reasons" in state_data and state_data["reasons"] is not None:
                    attrs["reasons"] = state_data["reasons"]
                self._attributes = attrs
                if self.hass is not None:
                    self.async_write_ha_state()
                break
