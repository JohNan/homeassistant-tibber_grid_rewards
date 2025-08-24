"""Daily reward tracker for Tibber Grid Reward."""
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = "tibber_grid_reward_daily_tracker"


class DailyRewardTracker:
    """Class to track daily grid rewards."""

    def __init__(self, hass: HomeAssistant):
        """Initialize the tracker."""
        self._hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data = {}
        self.daily_reward = 0.0

    async def async_load(self):
        """Load data from store."""
        stored_data = await self._store.async_load()
        if stored_data:
            self._data = stored_data
            self.daily_reward = self._data.get("daily_reward", 0.0)

    async def async_setup(self):
        """Set up the daily tracker."""
        await self.async_load()
        async_track_time_change(self._hass, self._reset_daily_reward, 0, 0, 0)

    @callback
    def _reset_daily_reward(self, now=None):
        """Reset the daily reward."""
        _LOGGER.debug("Resetting daily reward.")
        self._data["reward_at_start_of_day"] = self._data.get(
            "last_known_monthly_reward", 0.0
        )
        self.daily_reward = 0.0
        self._data["daily_reward"] = self.daily_reward
        self._hass.async_create_task(self._store.async_save(self._data))

    def update_monthly_reward(self, monthly_reward: float | None):
        """Update the monthly reward and calculate daily reward."""
        if monthly_reward is None:
            return

        reward_at_start_of_day = self._data.get("reward_at_start_of_day", 0.0)

        if monthly_reward < reward_at_start_of_day:
            _LOGGER.debug("New month detected, resetting start-of-day reward.")
            reward_at_start_of_day = 0.0
            self._data["reward_at_start_of_day"] = reward_at_start_of_day

        self.daily_reward = monthly_reward - reward_at_start_of_day
        self._data["daily_reward"] = self.daily_reward
        self._data["last_known_monthly_reward"] = monthly_reward
        
        self._hass.async_create_task(self._store.async_save(self._data))