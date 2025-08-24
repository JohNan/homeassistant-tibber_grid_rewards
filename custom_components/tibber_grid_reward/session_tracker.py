"""Reward session tracker for Tibber Grid Reward."""
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = "tibber_grid_reward_session_tracker"


class RewardSessionTracker:
    """Class to track reward sessions."""

    def __init__(self, hass: HomeAssistant):
        """Initialize the tracker."""
        self._hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data = {
            "active_session": None,
            "completed_sessions": [],
        }
        self._current_daily_reward = 0.0

    async def async_load(self):
        """Load data from store."""
        stored_data = await self._store.async_load()
        if stored_data:
            self._data = stored_data

    def update_state(self, new_state: str, current_daily_reward: float):
        """Update the session state."""
        self._current_daily_reward = current_daily_reward
        active_session = self._data.get("active_session")
        is_delivering = new_state == "GridRewardDelivering"

        if is_delivering and not active_session:
            # Start of a new session
            _LOGGER.debug("Starting new reward session.")
            self._data["active_session"] = {
                "start_time": dt_util.utcnow().isoformat(),
                "reward_at_start": current_daily_reward,
            }
            self._hass.async_create_task(self._store.async_save(self._data))

        elif not is_delivering and active_session:
            # End of a session
            _LOGGER.debug("Ending reward session.")
            start_time = dt_util.parse_datetime(active_session["start_time"])
            end_time = dt_util.utcnow()
            duration = end_time - start_time
            reward = current_daily_reward - active_session["reward_at_start"]

            completed_session = {
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_minutes": round(duration.total_seconds() / 60, 2),
                "reward": round(reward, 4),
            }
            self._data["completed_sessions"].append(completed_session)
            self._data["active_session"] = None
            self._hass.async_create_task(self._store.async_save(self._data))

    @property
    def last_session(self):
        """Return the last completed session."""
        if self._data["completed_sessions"]:
            return self._data["completed_sessions"][-1]
        return None

    @property
    def current_session_reward(self) -> float:
        """Return the reward for the current active session."""
        active_session = self._data.get("active_session")
        if not active_session:
            return 0.0
        
        reward = self._current_daily_reward - active_session["reward_at_start"]
        return round(reward, 4)