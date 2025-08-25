from unittest.mock import MagicMock
import pytest
from homeassistant.util import dt as dt_util

from custom_components.tibber_grid_reward.sensor import (
    GridRewardSensor,
    GridRewardCurrentDaySensor,
    RewardSessionSensor,
    FlexDeviceSensor,
    GRID_REWARD_SENSORS,
    FLEX_DEVICE_SENSORS,
)


@pytest.fixture
def mock_api():
    """Fixture for a mock Tibber API."""
    return MagicMock()


@pytest.fixture
def entry_id():
    """Fixture for a config entry ID."""
    return "test_entry_id"


@pytest.mark.parametrize(
    "description",
    GRID_REWARD_SENSORS,
)
async def test_grid_reward_sensors(mock_api, entry_id, description):
    """Test the GridRewardSensor."""
    sensor = GridRewardSensor(mock_api, entry_id, description)
    sensor.async_write_ha_state = MagicMock()

    assert sensor.name == description.name
    assert sensor.unique_id == f"{entry_id}_{description.key}"

    # Test update_data and state logic
    data = {
        "state": {
            "__typename": "GridRewardDelivering",
            "reasons": ["reason1", "reason2"],
            "reason": "delivering",
        },
        "rewardCurrentMonth": 100,
        "rewardCurrency": "EUR",
    }
    sensor.update_data(data)

    state = sensor._get_state(data)
    if description.key == "grid_reward_state":
        assert state == "GridRewardDelivering"
    elif description.key == "grid_reward_reason":
        assert state == "reason1, reason2"
    elif description.key == "grid_reward_current_month":
        assert state == 100
        assert sensor.native_unit_of_measurement == "EUR"

    sensor.async_write_ha_state.assert_called_once()


async def test_grid_reward_current_day_sensor(mock_api, entry_id):
    """Test the GridRewardCurrentDaySensor."""
    mock_tracker = MagicMock()
    mock_tracker.daily_reward = 10.5
    description = [d for d in GRID_REWARD_SENSORS if d.key == "grid_reward_current_day"][0]
    sensor = GridRewardCurrentDaySensor(mock_api, entry_id, mock_tracker, description)
    sensor.async_write_ha_state = MagicMock()

    assert sensor.name == "Grid Reward Current Day"
    assert sensor.unique_id == f"{entry_id}_grid_reward_current_day"

    data = {"rewardCurrency": "EUR"}
    sensor.update_data(data)
    state = sensor._get_state(data)
    assert state == 10.5
    assert sensor.native_unit_of_measurement == "EUR"
    sensor.async_write_ha_state.assert_called_once()


@pytest.mark.parametrize(
    "description",
    [d for d in GRID_REWARD_SENSORS if d.key in ("last_reward_session", "current_reward_session")],
)
async def test_reward_session_sensor(mock_api, entry_id, description):
    """Test the RewardSessionSensor."""
    mock_session_tracker = MagicMock()
    mock_session_tracker.last_session = {
        "start_time": "2023-01-01T12:00:00+00:00",
        "end_time": "2023-01-01T13:00:00+00:00",
        "duration_minutes": 60,
        "reward": 1.23,
    }
    mock_session_tracker.current_session_reward = 0.5
    sensor = RewardSessionSensor(mock_api, entry_id, mock_session_tracker, description)
    sensor.async_write_ha_state = MagicMock()

    assert sensor.name == description.name
    assert sensor.unique_id == f"{entry_id}_{description.key}"

    data = {"rewardCurrency": "EUR"}
    sensor.update_data(data)
    state = sensor._get_state(data)

    if description.key == "last_reward_session":
        assert state == dt_util.parse_datetime("2023-01-01T13:00:00+00:00")
        assert sensor.extra_state_attributes["reward"] == 1.23
    elif description.key == "current_reward_session":
        assert state == 0.5
        assert sensor.native_unit_of_measurement == "EUR"

    sensor.async_write_ha_state.assert_called_once()


@pytest.mark.parametrize("description", FLEX_DEVICE_SENSORS)
async def test_flex_device_sensor(mock_api, entry_id, description):
    """Test the FlexDeviceSensor."""
    device = {"id": "vehicle1", "type": "vehicle", "name": "My Car"}
    sensor = FlexDeviceSensor(mock_api, entry_id, device, description)
    sensor.async_write_ha_state = MagicMock()

    assert sensor.name == f"My Car {description.name}"
    assert sensor.unique_id == f"vehicle1_{description.key}"

    data = {
        "flexDevices": [
            {
                "vehicleId": "vehicle1",
                "state": {"__typename": "PluggedIn"},
                "isPluggedIn": True,
            }
        ]
    }
    sensor.update_data(data)
    
    device_data = data["flexDevices"][0]
    state = sensor._get_state(device_data)

    if description.key == "state":
        assert state == "PluggedIn"
    elif description.key == "connectivity":
        assert state == "Plugged In"
        assert sensor.icon == "mdi:car-electric"

    sensor.async_write_ha_state.assert_called_once()
