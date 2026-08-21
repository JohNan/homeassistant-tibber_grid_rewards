"""The Tibber Grid Reward integration."""

from homeassistant.config_entries import ConfigEntry, ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers import device_registry as dr

from .client import TibberAPI, TibberAuthError
from .const import DOMAIN
from .public_client import TibberPublicAPI
import logging
from .daily_tracker import DailyRewardTracker
from .session_tracker import RewardSessionTracker

PLATFORMS = ["sensor", "time", "binary_sensor"]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Tibber Grid Reward from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    client = get_async_client(hass, verify_ssl=False)

    api = TibberAPI(
        entry.data["username"],
        entry.data["password"],
        client,
    )

    try:
        await api.get_homes()  # Verify credentials
    except TibberAuthError as e:
        raise ConfigEntryAuthFailed from e

    daily_tracker = DailyRewardTracker(hass)
    await daily_tracker.async_setup()

    session_tracker = RewardSessionTracker(hass)
    await session_tracker.async_load()

    def update_grid_reward_sensors(data):
        """Update all grid reward sensors."""
        _LOGGER.debug("Grid reward callback triggered with data: %s", data)
        monthly_reward = data.get("rewardCurrentMonth")
        daily_tracker.update_monthly_reward(monthly_reward)
        
        grid_reward_state = data.get("state", {}).get("__typename")
        session_tracker.update_state(grid_reward_state, daily_tracker.daily_reward)

        for device in hass.data[DOMAIN][entry.entry_id]["grid_reward_devices"]:
            device.update_data(data)

    api.register_grid_reward_callback(update_grid_reward_sensors)
    
    entry.async_create_background_task(
        hass, api.subscribe_grid_reward(entry.data["home_id"]), "tibber-grid-reward-subscription"
    )

    api_key = entry.data.get("api_key") or entry.options.get("api_key")
    public_api = None
    if api_key:
        public_api = TibberPublicAPI(api_key, client)

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "public_api": public_api,
        "flex_devices": entry.data["flex_devices"],
        "grid_reward_devices": [],
        "vehicle_devices": {
            device["id"]: [] for device in entry.data["flex_devices"] if device["type"] == "vehicle"
        },
        "daily_tracker": daily_tracker,
        "session_tracker": session_tracker,
    }

    entry.async_on_unload(entry.add_update_listener(update_listener))

    def create_vehicle_update_callback(device_id):
        """Create a callback for a specific vehicle."""
        def update_vehicle_sensors(data):
            """Update all sensors for a specific vehicle."""
            _LOGGER.debug("Vehicle callback for %s triggered with data: %s", device_id, data)
            for sensor in hass.data[DOMAIN][entry.entry_id]["vehicle_devices"][device_id]:
                sensor.update_data(data)
        return update_vehicle_sensors

    for device in entry.data["flex_devices"]:
        if device["type"] == "vehicle":
            device_id = device["id"]
            callback = create_vehicle_update_callback(device_id)
            api.register_vehicle_callback(device_id, callback)
            entry.async_create_background_task(
                hass, api.subscribe_vehicle_state(device_id), f"tibber-vehicle-subscription-{device_id}"
            )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def set_departure_time(call: ServiceCall):
        """Handle the service call to set the departure time."""
        device_id = call.data.get("device_id")
        day = call.data.get("day")
        time_str = call.data.get("time")

        device_registry = dr.async_get(hass)
        device = device_registry.async_get(device_id)
        
        if not device:
            return

        vehicle_id = next(iter(device.identifiers))[1]
        
        await api.set_departure_time(
            home_id=entry.data["home_id"],
            vehicle_id=vehicle_id,
            day=day,
            time_str=time_str if time_str else None,
        )

    hass.services.async_register(DOMAIN, "set_departure_time", set_departure_time)

    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        hass.services.async_remove(DOMAIN, "set_departure_time")

    return unload_ok
