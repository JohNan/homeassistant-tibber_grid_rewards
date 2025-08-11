"""Platform for sensor integration."""
import logging
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.core import callback
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the sensor platform."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    api = entry_data["api"]
    flex_devices = entry_data["flex_devices"]
    daily_tracker = entry_data["daily_tracker"]
    session_tracker = entry_data["session_tracker"]

    grid_reward_sensors = [
        GridRewardStateSensor(api, config_entry.entry_id),
        GridRewardReasonSensor(api, config_entry.entry_id),
        GridRewardCurrentMonthSensor(api, config_entry.entry_id),
        GridRewardCurrentDaySensor(api, config_entry.entry_id, daily_tracker),
        LastRewardSessionSensor(api, config_entry.entry_id, session_tracker),
        CurrentRewardSessionSensor(api, config_entry.entry_id, session_tracker),
    ]
    entry_data["grid_reward_devices"].extend(grid_reward_sensors)
    async_add_entities(grid_reward_sensors)

    for device in flex_devices:
        if device["type"] == "vehicle":
            vehicle_sensors = [
                VehicleBatterySensor(api, config_entry.entry_id, device),
            ]
            entry_data["vehicle_devices"][device["id"]].extend(vehicle_sensors)
            async_add_entities(vehicle_sensors)

        # The FlexDevice sensors are updated from the grid reward subscription
        flex_sensors = [
            FlexDeviceStateSensor(api, config_entry.entry_id, device),
            FlexDeviceConnectivitySensor(api, config_entry.entry_id, device),
        ]
        entry_data["grid_reward_devices"].extend(flex_sensors)
        async_add_entities(flex_sensors)


class GridRewardSensor(SensorEntity):
    """Base class for Tibber Grid Reward sensors."""

    def __init__(self, api, entry_id):
        self._api = api
        self._entry_id = entry_id
        self._attributes = {}

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "Tibber Grid Reward",
            "manufacturer": "Tibber",
        }

    @callback
    def update_data(self, data):
        _LOGGER.debug("Updating grid reward sensor %s with data: %s", self.unique_id, data)
        self._attributes = data
        self.async_write_ha_state()

class GridRewardStateSensor(GridRewardSensor):
    """Representation of a Grid Reward State Sensor."""
    @property
    def unique_id(self):
        return f"{self._entry_id}_grid_reward_state"
    @property
    def name(self):
        return "Grid Reward State"
    @property
    def state(self):
        return self._attributes.get("state", {}).get("__typename")

class GridRewardReasonSensor(GridRewardSensor):
    """Representation of a Grid Reward Reason Sensor."""
    @property
    def unique_id(self):
        return f"{self._entry_id}_grid_reward_reason"
    @property
    def name(self):
        return "Grid Reward Reason"
    @property
    def state(self):
        reasons = self._attributes.get("state", {}).get("reasons")
        if reasons:
            return ", ".join(reasons)
        return self._attributes.get("state", {}).get("reason")

class GridRewardCurrentMonthSensor(GridRewardSensor):
    """Representation of a Grid Reward Current Month Sensor."""
    @property
    def unique_id(self):
        return f"{self._entry_id}_grid_reward_current_month"
    @property
    def name(self):
        return "Grid Reward Current Month"
    @property
    def state(self):
        return self._attributes.get("rewardCurrentMonth")
    @property
    def unit_of_measurement(self):
        return self._attributes.get("rewardCurrency")
    @property
    def device_class(self):
        return SensorDeviceClass.MONETARY

class GridRewardCurrentDaySensor(GridRewardSensor):
    """Representation of a Grid Reward Current Day Sensor."""

    def __init__(self, api, entry_id, tracker):
        """Initialize the sensor."""
        super().__init__(api, entry_id)
        self._tracker = tracker

    @property
    def unique_id(self):
        return f"{self._entry_id}_grid_reward_current_day"
    @property
    def name(self):
        return "Grid Reward Current Day"
    @property
    def state(self):
        return round(self._tracker.daily_reward, 2)
    @property
    def unit_of_measurement(self):
        return self._attributes.get("rewardCurrency")
    @property
    def device_class(self):
        return SensorDeviceClass.MONETARY


class LastRewardSessionSensor(GridRewardSensor):
    """Representation of the last reward session."""

    def __init__(self, api, entry_id, session_tracker):
        """Initialize the sensor."""
        super().__init__(api, entry_id)
        self._session_tracker = session_tracker

    @property
    def unique_id(self):
        return f"{self._entry_id}_last_reward_session"

    @property
    def name(self):
        return "Last Reward Session"

    @property
    def state(self):
        last_session = self._session_tracker.last_session
        if last_session:
            return last_session["end_time"]
        return None

    @property
    def device_class(self):
        return SensorDeviceClass.TIMESTAMP

    @property
    def extra_state_attributes(self):
        last_session = self._session_tracker.last_session
        if last_session:
            return {
                "start_time": last_session["start_time"],
                "end_time": last_session["end_time"],
                "duration_minutes": last_session["duration_minutes"],
                "reward": last_session["reward"],
                "currency": self._attributes.get("rewardCurrency"),
            }
        return {}

class CurrentRewardSessionSensor(GridRewardSensor):
    """Representation of the current reward session sensor."""

    def __init__(self, api, entry_id, session_tracker):
        """Initialize the sensor."""
        super().__init__(api, entry_id)
        self._session_tracker = session_tracker

    @property
    def unique_id(self):
        return f"{self._entry_id}_current_reward_session"

    @property
    def name(self):
        return "Current Reward Session"

    @property
    def state(self):
        return self._session_tracker.current_session_reward

    @property
    def unit_of_measurement(self):
        return self._attributes.get("rewardCurrency")

    @property
    def device_class(self):
        return SensorDeviceClass.MONETARY

class FlexDeviceSensor(SensorEntity):
    """Base class for Flex Device sensors."""
    def __init__(self, api, entry_id, device):
        self._api = api
        self._entry_id = entry_id
        self._device_id = device["id"]
        self._device_type = device["type"]
        self._device_name = device.get("name", self._device_id)
        self._attributes = {}

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
        _LOGGER.debug("Updating flex device sensor %s with data: %s", self.unique_id, data)
        flex_devices = data.get("flexDevices", [])
        device_id_key = "vehicleId" if self._device_type == "vehicle" else "batteryId"
        for device in flex_devices:
            if device.get(device_id_key) == self._device_id:
                self._attributes = device
                self.async_write_ha_state()
                break

class FlexDeviceStateSensor(FlexDeviceSensor):
    """Representation of a Flex Device State Sensor."""
    @property
    def unique_id(self):
        return f"{self._device_id}_state"
    @property
    def name(self):
        return f"{self._device_name} State"
    @property
    def state(self):
        return self._attributes.get("state", {}).get("__typename")

class FlexDeviceConnectivitySensor(FlexDeviceSensor):
    """Representation of a Flex Device Connectivity Sensor."""
    @property
    def unique_id(self):
        return f"{self._device_id}_connectivity"
    @property
    def name(self):
        return f"{self._device_name} Connectivity"
    @property
    def state(self):
        if self._device_type == "vehicle":
            return "Plugged In" if self._attributes.get("isPluggedIn") else "Unplugged"
        return "Online" # Placeholder for battery
    @property
    def icon(self):
        if self._device_type == "vehicle":
            return "mdi:car-electric" if self.state == "Plugged In" else "mdi:car-electric-outline"
        return "mdi:battery"

class VehicleSensor(SensorEntity):
    """Base class for Vehicle sensors."""
    def __init__(self, api, entry_id, device):
        self._api = api
        self._entry_id = entry_id
        self._device_id = device["id"]
        self._device_name = device.get("name", self._device_id)
        self._attributes = {}

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
        _LOGGER.debug("Updating vehicle sensor %s with data: %s", self.unique_id, data)
        self._attributes = data
        self.async_write_ha_state()

class VehicleBatterySensor(VehicleSensor):
    """Representation of a Vehicle Battery Sensor."""
    @property
    def unique_id(self):
        return f"{self._device_id}_battery"
    @property
    def name(self):
        return f"{self._device_name} Battery"
    @property
    def state(self):
        return self._attributes.get("battery", {}).get("percent")
    @property
    def device_class(self):
        return SensorDeviceClass.BATTERY
    @property
    def unit_of_measurement(self):
        return "%"
