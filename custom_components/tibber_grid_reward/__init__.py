"""The Tibber Grid Reward integration."""

import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.httpx_client import get_async_client

from .client import TibberAPI, TibberAuthError
from .const import DOMAIN
from .daily_tracker import DailyRewardTracker
from .hub import TibberAccountHub
from .public_client import TibberPublicAPI
from .session_tracker import RewardSessionTracker

PLATFORMS = ["sensor", "time", "binary_sensor", "number", "switch"]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Tibber Grid Reward from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    accounts = hass.data.setdefault(f"{DOMAIN}_accounts", {})

    client = get_async_client(hass)
    username = entry.data["username"]

    # Migrate legacy unique_id (username) to scoped unique_id (username_home_id)
    if entry.unique_id == username:
        new_unique_id = f"{username}_{entry.data['home_id']}"
        _LOGGER.debug(
            "Migrating config entry unique ID from %s to %s",
            entry.unique_id,
            new_unique_id,
        )
        hass.config_entries.async_update_entry(entry, unique_id=new_unique_id)

    api_key = entry.data.get("api_key") or entry.options.get("api_key")

    if username in accounts:
        hub: TibberAccountHub = accounts[username]
        api = hub.api
        if api_key and (not hub.public_api or hub.public_api._token != api_key):
            hub.public_api = TibberPublicAPI(api_key, client)
        public_api = hub.public_api
    else:
        api = TibberAPI(
            username,
            entry.data["password"],
            client,
        )
        try:
            await api.get_homes()  # Verify credentials
        except TibberAuthError as e:
            raise ConfigEntryAuthFailed from e

        public_api = None
        if api_key:
            public_api = TibberPublicAPI(api_key, client)

        hub = TibberAccountHub(hass, username, api, public_api)
        accounts[username] = hub

    daily_tracker = DailyRewardTracker(hass)
    await daily_tracker.async_setup()

    session_tracker = RewardSessionTracker(hass)
    await session_tracker.async_load()

    hass.data[DOMAIN][entry.entry_id] = {
        "hub": hub,
        "api": api,
        "public_api": public_api,
        "flex_devices": entry.data["flex_devices"],
        "grid_reward_devices": [],
        "battery_coordinators": {},
        "vehicle_devices": {
            device["id"]: []
            for device in entry.data["flex_devices"]
            if device["type"] == "vehicle"
        },
        "daily_tracker": daily_tracker,
        "session_tracker": session_tracker,
    }

    @callback
    def update_grid_reward_sensors(data):
        """Update all grid reward sensors."""
        _LOGGER.debug("Grid reward callback triggered with data: %s", data)
        entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if not entry_data:
            return

        monthly_reward = data.get("rewardCurrentMonth")
        daily_tracker.update_monthly_reward(monthly_reward)

        grid_reward_state = data.get("state", {}).get("__typename")
        session_tracker.update_state(grid_reward_state, daily_tracker.daily_reward)

        for device in entry_data.get("grid_reward_devices", []):
            device.update_data(data)

        for coordinator in entry_data.get("battery_coordinators", {}).values():
            coordinator.async_request_refresh()

    def create_vehicle_update_callback(device_id):
        """Create a callback for a specific vehicle."""

        @callback
        def update_vehicle_sensors(data):
            """Update all sensors for a specific vehicle."""
            _LOGGER.debug(
                "Vehicle callback for %s triggered with data: %s", device_id, data
            )
            entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if not entry_data:
                return

            # Iterate a snapshot: some entries (e.g. number.py's battery
            # level manager) may add/remove themselves from this list in
            # response to this very update.
            vehicle_devices = entry_data.get("vehicle_devices", {}).get(device_id, [])
            for sensor in list(vehicle_devices):
                sensor.update_data(data)

        return update_vehicle_sensors

    vehicle_callbacks = {}
    for device in entry.data["flex_devices"]:
        if device["type"] == "vehicle":
            device_id = device["id"]
            vehicle_callbacks[device_id] = create_vehicle_update_callback(device_id)

    hub.register_home(entry, update_grid_reward_sensors, vehicle_callbacks)

    entry.async_on_unload(entry.add_update_listener(update_listener))

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
        target_entry_id = next(iter(device.config_entries), None)
        if not target_entry_id or target_entry_id not in hass.data.get(DOMAIN, {}):
            return

        entry_data = hass.data[DOMAIN][target_entry_id]
        target_api = entry_data["api"]
        target_entry = hass.config_entries.async_get_entry(target_entry_id)
        if not target_entry:
            return

        await target_api.set_departure_time(
            home_id=target_entry.data["home_id"],
            vehicle_id=vehicle_id,
            day=day,
            time_str=time_str if time_str else None,
        )

    if not hass.services.has_service(DOMAIN, "set_departure_time"):
        hass.services.async_register(DOMAIN, "set_departure_time", set_departure_time)

    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        username = entry.data.get("username")
        accounts = hass.data.get(f"{DOMAIN}_accounts", {})
        hub: TibberAccountHub | None = accounts.get(username)

        if hub:
            hub.unregister_home(entry.entry_id)
            if not hub.has_entries():
                await hub.async_close()
                accounts.pop(username, None)

        hass.data[DOMAIN].pop(entry.entry_id, None)

        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "set_departure_time")

    return unload_ok
