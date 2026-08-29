"""Platform for sensor integration."""
import asyncio
import logging
from datetime import timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
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


BATTERY_SAVINGS_SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="TODAY",
        name="Savings Today",
        device_class=SensorDeviceClass.MONETARY,
    ),
    SensorEntityDescription(
        key="WEEK",
        name="Savings This Week",
        device_class=SensorDeviceClass.MONETARY,
    ),
    SensorEntityDescription(
        key="MONTH",
        name="Savings This Month",
        device_class=SensorDeviceClass.MONETARY,
    ),
)

# The savings figures move slowly, so there is no point polling them at the
# platform's default interval. One battery fetch per interval is shared by all
# three period sensors.
SAVINGS_MIN_INTERVAL = timedelta(minutes=10)


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

VEHICLE_BATTERY_SENSOR_DESCRIPTION = SensorEntityDescription(
    key="battery_level",
    name="Battery Level",
    device_class=SensorDeviceClass.BATTERY,
    native_unit_of_measurement=PERCENTAGE,
    state_class=SensorStateClass.MEASUREMENT,
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

    grid_reward_sensors = []
    for description in GRID_REWARD_SENSORS:
        if description.key == "grid_reward_current_day":
            grid_reward_sensors.append(
                GridRewardCurrentDaySensor(
                    api, config_entry.entry_id, daily_tracker, description
                )
            )
        elif description.key in ("last_reward_session", "current_reward_session"):
            grid_reward_sensors.append(
                RewardSessionSensor(
                    api, config_entry.entry_id, session_tracker, description
                )
            )
        else:
            grid_reward_sensors.append(
                GridRewardSensor(api, config_entry.entry_id, description)
            )

    for device in flex_devices:
        for description in FLEX_DEVICE_SENSORS:
            grid_reward_sensors.append(
                FlexDeviceSensor(api, config_entry.entry_id, device, description)
            )
        if device.get("type") == "battery":
            fetcher = BatterySavingsFetcher(
                api, config_entry.data["home_id"], device["id"]
            )
            sensors.extend(
                BatterySavingsSensor(
                    fetcher, config_entry.entry_id, device, description
                )
                for description in BATTERY_SAVINGS_SENSORS
            )
        if device.get("type") == "vehicle":
            vehicle_id = device["id"]
            battery_sensor = VehicleBatterySensor(api, config_entry.entry_id, device)
            sensors.append(battery_sensor)
            if (
                "vehicle_devices" in entry_data
                and vehicle_id in entry_data["vehicle_devices"]
            ):
                entry_data["vehicle_devices"][vehicle_id].append(battery_sensor)

    hass.data[DOMAIN][config_entry.entry_id]["grid_reward_devices"].extend(
        grid_reward_sensors
    )
    sensors.extend(grid_reward_sensors)
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
        if self.hass is not None:
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


class BatterySavingsFetcher:
    """Throttled, shared fetcher for a battery's aggregated savings.

    The three period sensors would otherwise each hit the API on every poll for
    a figure that barely moves. This fetches once per SAVINGS_MIN_INTERVAL and
    hands the same result to all of them.
    """

    def __init__(self, api, home_id: str, battery_id: str):
        self._api = api
        self._home_id = home_id
        self._battery_id = battery_id
        self._data: dict = {}
        self._fetched_at = None
        self._lock = asyncio.Lock()

    async def async_get(self) -> dict:
        """Return the savings mapping, refreshing it if it has gone stale."""
        async with self._lock:
            now = dt_util.utcnow()
            if (
                self._fetched_at is None
                or now - self._fetched_at >= SAVINGS_MIN_INTERVAL
            ):
                self._data = await self._api.get_battery_savings(
                    self._home_id, self._battery_id
                )
                self._fetched_at = now
        return self._data


class BatterySavingsSensor(SensorEntity):
    """Savings for one aggregation period of one battery."""

    entity_description: SensorEntityDescription

    def __init__(self, fetcher, entry_id, device, description: SensorEntityDescription):
        self.entity_description = description
        self._fetcher = fetcher
        self._entry_id = entry_id
        self._device_id = device["id"]
        self._device_name = device.get("name", self._device_id)
        self._attr_unique_id = f"{self._device_id}_savings_{description.key.lower()}"
        self._attr_name = f"{self._device_name} {description.name}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": "Tibber",
            "via_device": (DOMAIN, self._entry_id),
        }

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        data = await self._fetcher.async_get()
        item = data.get(self.entity_description.key)
        if not item:
            # The API returns no total for a period that has not accrued
            # anything yet, which is normal early in the day.
            self._attr_native_value = None
            return
        self._attr_native_value = item.get("value")
        self._attr_native_unit_of_measurement = item.get("unit")


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
                if self.hass is not None:
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

    def __init__(
        self,
        public_api: TibberPublicAPI,
        home_id: str,
        entry_id: str,
        description: SensorEntityDescription,
    ):
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
        if not price_info:
            return

        now = dt_util.now()
        current_hour = now.replace(minute=0, second=0, microsecond=0)

        today_prices_data = price_info.get("today", [])
        tomorrow_prices_data = price_info.get("tomorrow", [])
        all_prices_data = today_prices_data + tomorrow_prices_data

        def is_current_hour(price_dict):
            starts_at_str = price_dict.get("startsAt")
            if not starts_at_str:
                return False
            dt = dt_util.parse_datetime(starts_at_str)
            if not dt:
                return False
            return dt == current_hour

        current_price = next(
            (p for p in all_prices_data if is_current_hour(p)), None
        )

        if current_price:
            self._attr_native_value = current_price.get("total")
            if "currency" in current_price:
                self._attr_native_unit_of_measurement = current_price["currency"]

        all_prices = [
            p["total"] for p in all_prices_data if p.get("total") is not None
        ]

        def get_price_rating(price, prices):
            if not prices or price is None:
                return None

            p_count = len(prices)
            if p_count == 0 or len(set(prices)) == 1:
                return "Normal"

            lower_prices = sum(1 for p in prices if p < price)
            percentile = lower_prices / p_count

            if percentile < 0.33:
                return "Low"
            if percentile < 0.66:
                return "Moderate"
            return "High"

        today_prices_total = [p.get("total") for p in today_prices_data]
        tomorrow_prices_total = [p.get("total") for p in tomorrow_prices_data]

        self._attr_extra_state_attributes = {
            "last_update": now.isoformat(),
            "today": ", ".join(map(str, today_prices_total)),
            "today_raw": [
                {
                    "time": p.get("startsAt"),
                    "price": p.get("total"),
                    "rating": get_price_rating(p.get("total"), all_prices),
                }
                for p in today_prices_data
            ],
            "tomorrow": ", ".join(map(str, tomorrow_prices_total))
            if tomorrow_prices_total
            else None,
            "tomorrow_raw": [
                {
                    "time": p.get("startsAt"),
                    "price": p.get("total"),
                    "rating": get_price_rating(p.get("total"), all_prices),
                }
                for p in tomorrow_prices_data
            ]
            if tomorrow_prices_data
            else None,
            "tomorrow_valid": bool(tomorrow_prices_data),
        }


class VehicleBatterySensor(SensorEntity):
    """Representation of a vehicle battery level sensor."""

    entity_description = VEHICLE_BATTERY_SENSOR_DESCRIPTION

    def __init__(self, api, entry_id: str, device: dict):
        """Initialize the vehicle battery sensor."""
        self._api = api
        self._entry_id = entry_id
        self._device_id = device["id"]
        self._device_name = device.get("name", self._device_id)
        self._attr_unique_id = f"{self._device_id}_battery_level"
        self._attr_name = f"{self._device_name} Battery Level"
        self._attr_native_value = None

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
    def update_data(self, data: dict) -> None:
        """Update entity with vehicle state data."""
        _LOGGER.debug(
            "Updating vehicle battery sensor %s with data: %s", self.unique_id, data
        )
        battery = data.get("battery")
        if isinstance(battery, dict):
            level = battery.get("level")
            if level is not None:
                try:
                    self._attr_native_value = int(level)
                except (ValueError, TypeError):
                    self._attr_native_value = level
                if self.hass is not None:
                    self.async_write_ha_state()
                return

        for setting in data.get("userSettings", []):
            if setting.get("key") in ("batteryLevel", "offline.vehicle.batteryLevel"):
                val = setting.get("value")
                if val is not None:
                    try:
                        self._attr_native_value = int(val)
                    except (ValueError, TypeError):
                        self._attr_native_value = val
                    if self.hass is not None:
                        self.async_write_ha_state()
                    return
