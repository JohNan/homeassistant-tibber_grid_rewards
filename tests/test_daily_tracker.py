"""Tests for the DailyRewardTracker."""
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import pytest

from custom_components.tibber_grid_reward.daily_tracker import DailyRewardTracker


@pytest.fixture
def mock_hass():
    """Fixture for a mock Home Assistant instance."""
    hass = MagicMock()
    # Make sure when a task is created, it's awaited
    hass.async_create_task.side_effect = lambda coro: asyncio.create_task(coro)
    return hass


@pytest.fixture
@patch("custom_components.tibber_grid_reward.daily_tracker.Store")
def tracker(MockStore, mock_hass):
    """Fixture for a DailyRewardTracker instance."""
    mock_store = MockStore.return_value
    mock_store.async_load = AsyncMock(return_value={})
    mock_store.async_save = AsyncMock()

    tracker_instance = DailyRewardTracker(mock_hass)
    tracker_instance._store = mock_store
    return tracker_instance


@patch("custom_components.tibber_grid_reward.daily_tracker.async_track_time_change")
async def test_async_setup(mock_track_time, tracker):
    """Test the setup of the daily tracker."""
    await tracker.async_setup()
    tracker._store.async_load.assert_awaited_once()
    mock_track_time.assert_called_once_with(
        tracker._hass, tracker._reset_daily_reward, 0, 0, 0
    )


async def test_update_monthly_reward(tracker):
    """Test updating the monthly reward."""
    tracker._data["reward_at_start_of_day"] = 100.0
    tracker.update_monthly_reward(110.5)
    await asyncio.sleep(0)
    assert tracker.daily_reward == 10.5
    assert tracker._data["daily_reward"] == 10.5
    assert tracker._data["last_known_monthly_reward"] == 110.5
    tracker._store.async_save.assert_awaited_once()


async def test_update_monthly_reward_new_month(tracker):
    """Test updating the monthly reward when a new month starts."""
    tracker._data["reward_at_start_of_day"] = 100.0
    # Simulate new month where API returns a lower value than the start-of-day value
    tracker.update_monthly_reward(5.0)
    await asyncio.sleep(0)
    # reward_at_start_of_day should be reset to 0
    assert tracker._data["reward_at_start_of_day"] == 0.0
    # daily_reward should be the new monthly reward
    assert tracker.daily_reward == 5.0
    tracker._store.async_save.assert_awaited_once()


async def test_reset_daily_reward(tracker):
    """Test the reset daily reward callback."""
    tracker._data["last_known_monthly_reward"] = 150.0
    tracker.daily_reward = 50.0

    tracker._reset_daily_reward()
    await asyncio.sleep(0)

    assert tracker.daily_reward == 0.0
    assert tracker._data["daily_reward"] == 0.0
    assert tracker._data["reward_at_start_of_day"] == 150.0
    tracker._store.async_save.assert_awaited_once()
