"""Platform for sensor integration."""
import logging
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorEntityDescription,
)
from homeassistant.core import callback
from homeassistant.util import dt as dt_util
from .const import DOMAIN
from .public_client import TibberPublicAPI

_LOGGER = logging.getLogger(__name__)


PRICE_SENSOR_DESCRIPTION = SensorEntityDescription(
    key="current_price",
    name="Current Price",
    device_class=SensorDeviceClass.MONETARY,
)


GRID_REWARD_SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="grid_reward_state",
        name="Grid Reward State",
    ),
    SensorEntityDescription(
        key="grid_reward_reason",
        name="Grid Reward Reason",
    ),
    SensorEntityDescription(
        key="grid_reward_current_month",
        name="Grid Reward Current Month",
        device_class=SensorDeviceClass.MONETARY,
    ),
    SensorEntityDescription(
        key="grid_reward_current_day",
        name="Grid Reward Current Day",
        device_class=SensorDeviceClass.MONETARY,
    ),
    SensorEntityDescription(
        key="last_reward_session",
        name="Last Reward Session",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="current_reward_session",
        name="Current Reward Session",
        device_class=SensorDeviceClass.MONETARY,
    ),
)

FLEX_DEVICE_SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="state",
        name="State",
    ),
    SensorEntityDescription(
        key="connectivity",
        name="Connectivity",
    ),
)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the sensor platform."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    api = entry_data["api"]
    public_api = entry_data.get("public_api")
    flex_devices = entry_data["flex_devices"]
    daily_tracker = entry_data["daily_tracker"]
    session_tracker = entry_data["session_tracker"]

    sensors = []
    if public_api:
        sensors.append(
            PriceSensor(
                public_api,
                config_entry.data["home_id"],
                config_entry.entry_id,
                PRICE_SENSOR_DESCRIPTION,
            )
        )

    for description in GRID_REWARD_SENSORS:
        if description.key == "grid_reward_current_day":
            sensors.append(
                GridRewardCurrentDaySensor(
                    api, config_entry.entry_id, daily_tracker, description
                )
            )
        elif description.key in ("last_reward_session", "current_reward_session"):
            sensors.append(
                RewardSessionSensor(
                    api, config_entry.entry_id, session_tracker, description
                )
            )
        else:
            sensors.append(
                GridRewardSensor(api, config_entry.entry_id, description)
            )

    for device in flex_devices:
        for description in FLEX_DEVICE_SENSORS:
            sensors.append(
                FlexDeviceSensor(api, config_entry.entry_id, device, description)
            )

    hass.data[DOMAIN][config_entry.entry_id]["grid_reward_devices"].extend(sensors)
    async_add_entities(sensors)


class GridRewardSensor(SensorEntity):
    """Base class for Tibber Grid Reward sensors."""

    entity_description: SensorEntityDescription

    def __init__(self, api, entry_id, description: SensorEntityDescription):
        self.entity_description = description
        self._api = api
        self._entry_id = entry_id
        self._attributes = {}
        self._attr_unique_id = f"{self._entry_id}_{description.key}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "Tibber Grid Reward",
            "manufacturer": "Tibber",
        }

    @callback
    def update_data(self, data):
        _LOGGER.debug(
            "Updating grid reward sensor %s with data: %s", self.unique_id, data
        )
        self._attributes = data
        self._attr_native_value = self._get_state(data)
        self.async_write_ha_state()

    def _get_state(self, data):
        """Get the state of the sensor."""
        if self.entity_description.key == "grid_reward_state":
            return data.get("state", {}).get("__typename")
        if self.entity_description.key == "grid_reward_reason":
            reasons = data.get("state", {}).get("reasons")
            if reasons:
                return ", ".join(reasons)
            return data.get("state", {}).get("reason")
        if self.entity_description.key == "grid_reward_current_month":
            self._attr_native_unit_of_measurement = data.get("rewardCurrency")
            return data.get("rewardCurrentMonth")
        return None


class GridRewardCurrentDaySensor(GridRewardSensor):
    """Representation of a Grid Reward Current Day Sensor."""

    def __init__(self, api, entry_id, tracker, description: SensorEntityDescription):
        """Initialize the sensor."""
        super().__init__(api, entry_id, description)
        self._tracker = tracker

    def _get_state(self, data):
        """Get the state of the sensor."""
        self._attr_native_unit_of_measurement = data.get("rewardCurrency")
        return round(self._tracker.daily_reward, 2)


class RewardSessionSensor(GridRewardSensor):
    """Representation of a reward session sensor."""

    def __init__(
        self, api, entry_id, session_tracker, description: SensorEntityDescription
    ):
        """Initialize the sensor."""
        super().__init__(api, entry_id, description)
        self._session_tracker = session_tracker

    def _get_state(self, data):
        """Get the state of the sensor."""
        if self.entity_description.key == "last_reward_session":
            last_session = self._session_tracker.last_session
            if last_session:
                self._attr_extra_state_attributes = {
                    "start_time": last_session["start_time"],
                    "end_time": last_session["end_time"],
                    "duration_minutes": last_session["duration_minutes"],
                    "reward": last_session["reward"],
                    "currency": data.get("rewardCurrency"),
                }
                return dt_util.parse_datetime(last_session["end_time"])
            return None
        if self.entity_description.key == "current_reward_session":
            self._attr_native_unit_of_measurement = data.get("rewardCurrency")
            return self._session_tracker.current_session_reward
        return None


class FlexDeviceSensor(SensorEntity):
    """Base class for Flex Device sensors."""

    entity_description: SensorEntityDescription

    def __init__(self, api, entry_id, device, description: SensorEntityDescription):
        self.entity_description = description
        self._api = api
        self._entry_id = entry_id
        self._device_id = device["id"]
        self._device_type = device["type"]
        self._device_name = device.get("name", self._device_id)
        self._attributes = {}
        self._attr_unique_id = f"{self._device_id}_{description.key}"
        self._attr_name = f"{self._device_name} {description.name}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": "Tibber",
            "via_device": (DOMAIN, self._entry_id),
        }

    @callback
    def update_data(self, data):
        _LOGGER.debug(
            "Updating flex device sensor %s with data: %s", self.unique_id, data
        )
        flex_devices = data.get("flexDevices", [])
        device_id_key = (
            "vehicleId" if self._device_type == "vehicle" else "batteryId"
        )
        for device in flex_devices:
            if device.get(device_id_key) == self._device_id:
                self._attributes = device
                self._attr_native_value = self._get_state(device)
                self.async_write_ha_state()
                break

    def _get_state(self, data):
        """Get the state of the sensor."""
        if self.entity_description.key == "state":
            return data.get("state", {}).get("__typename")
        if self.entity_description.key == "connectivity":
            if self._device_type == "vehicle":
                is_plugged_in = data.get("isPluggedIn")
                self._attr_icon = (
                    "mdi:car-electric"
                    if is_plugged_in
                    else "mdi:car-electric-outline"
                )
                return "Plugged In" if is_plugged_in else "Unplugged"
            self._attr_icon = "mdi:battery"
            return "Online"  # Placeholder for battery
        return None


class PriceSensor(SensorEntity):
    """Representation of a Tibber price sensor."""

    entity_description: SensorEntityDescription

    def __init__(self, public_api: TibberPublicAPI, home_id: str, entry_id: str, description: SensorEntityDescription):
        """Initialize the sensor."""
        self.entity_description = description
        self._public_api = public_api
        self._home_id = home_id
        self._entry_id = entry_id
        self._attr_unique_id = f"{self._entry_id}_{description.key}"
        self._attr_extra_state_attributes = {}

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "Tibber Grid Reward",
            "manufacturer": "Tibber",
        }

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        price_info = await self._public_api.get_price_info(self._home_id)
        if price_info:
            current_price = price_info.get("current")
            if current_price:
                self._attr_native_value = current_price.get("total")
                # Note: The currency is not available in the priceInfo query from the public API
                # in the same way as the private API. This will be addressed later if possible.

            self._attr_extra_state_attributes["today"] = price_info.get("today")
            self._attr_extra_state_attributes["tomorrow"] = price_info.get("tomorrow")
