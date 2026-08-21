"""Platform for switch integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    """Set up the switch platform."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    api = entry_data["api"]
    flex_devices = entry_data["flex_devices"]

    entities = []
    for device in flex_devices:
        if device["type"] == "vehicle":
            vehicle_id = device["id"]
            entity = SmartChargingSwitch(api, config_entry.entry_id, device)
            entities.append(entity)
            entry_data["grid_reward_devices"].append(entity)
            entry_data["vehicle_devices"][vehicle_id].append(entity)

    async_add_entities(entities)


class SmartChargingSwitch(SwitchEntity):
    """Representation of a Smart Charging switch entity."""

    def __init__(self, api, entry_id: str, device: dict[str, Any]):
        """Initialize the switch entity."""
        self._api = api
        self._entry_id = entry_id
        self._home_id = api.home_id
        self._device_id = device["id"]
        self._device_name = device.get("name", self._device_id)
        self._attr_name = f"{self._device_name} Smart Charging"
        self._attr_unique_id = f"{self._device_id}_smart_charging_switch"
        self._attr_icon = "mdi:ev-station"
        self._attr_is_on = None

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": "Tibber",
            "via_device": (DOMAIN, self._entry_id),
        }

    @callback
    def update_data(self, data: dict[str, Any]) -> None:
        """Update the entity from grid reward or vehicle state data."""
        _LOGGER.debug("Updating SmartChargingSwitch for %s with data: %s", self.entity_id, data)

        # Check gridRewardStatus update
        flex_devices = data.get("flexDevices", [])
        for dev in flex_devices:
            if dev.get("vehicleId") == self._device_id and "isSmartChargingEnabled" in dev:
                self._attr_is_on = dev["isSmartChargingEnabled"]
                self.async_write_ha_state()
                return

        # Check vehicleState update (userSettings)
        user_settings = data.get("userSettings", [])
        for setting in user_settings:
            if setting.get("key") in (
                "online.vehicle.smartCharging.isEnabled",
                "offline.vehicle.smartCharging.isEnabled",
                "online.vehicle.smartCharging.enabled",
            ):
                val = setting.get("value")
                if isinstance(val, bool):
                    self._attr_is_on = val
                elif isinstance(val, str):
                    self._attr_is_on = val.lower() == "true"
                self.async_write_ha_state()
                return

        # Check vehicleState update (smartChargingStatus)
        if "smartChargingStatus" in data:
            status = data.get("smartChargingStatus")
            if status is not None:
                if isinstance(status, bool):
                    self._attr_is_on = status
                elif isinstance(status, str):
                    self._attr_is_on = status.lower() in ("enabled", "active", "true", "on")
                self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the smart charging switch on."""
        _LOGGER.debug("Turning on Smart Charging for %s", self.entity_id)
        await self._api.set_smart_charging_enabled(
            home_id=self._home_id,
            vehicle_id=self._device_id,
            enabled=True,
        )
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the smart charging switch off."""
        _LOGGER.debug("Turning off Smart Charging for %s", self.entity_id)
        await self._api.set_smart_charging_enabled(
            home_id=self._home_id,
            vehicle_id=self._device_id,
            enabled=False,
        )
        self._attr_is_on = False
        self.async_write_ha_state()
