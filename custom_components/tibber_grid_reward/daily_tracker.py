"""Daily reward tracker for Tibber Grid Reward."""
import logging
from datetime import date

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

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
        
        today = dt_util.now().date()
        last_updated_str = self._data.get("last_updated")
        if last_updated_str:
            last_updated = date.fromisoformat(last_updated_str)
            if last_updated < today:
                _LOGGER.debug("New day, resetting daily reward.")
                self._data["reward_at_start_of_day"] = self._data.get(
                    "last_known_monthly_reward", 0.0
                )
                self.daily_reward = 0.0
                self._data["daily_reward"] = self.daily_reward
        
        self._data["last_updated"] = today.isoformat()
        await self._store.async_save(self._data)

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
        self._data["last_updated"] = dt_util.now().date().isoformat()
        
        self._hass.async_create_task(self._store.async_save(self._data))
