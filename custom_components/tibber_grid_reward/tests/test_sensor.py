from unittest.mock import MagicMock
import pytest

from custom_components.tibber_grid_reward.sensor import (
    GridRewardStateSensor,
    GridRewardReasonSensor,
    GridRewardCurrentMonthSensor,
    GridRewardCurrentDaySensor,
    FlexDeviceStateSensor,
    FlexDeviceConnectivitySensor,
)

@pytest.fixture
def mock_api():
    return MagicMock()

@pytest.fixture
def entry_id():
    return "test_entry_id"

def test_grid_reward_state_sensor(mock_api, entry_id):
    sensor = GridRewardStateSensor(mock_api, entry_id)
    sensor.async_write_ha_state = MagicMock()
    assert sensor.name == "Grid Reward State"
    assert sensor.unique_id == f"{entry_id}_grid_reward_state"
    sensor.update_data({"state": {"__typename": "GridRewardDelivering"}})
    assert sensor.state == "GridRewardDelivering"
    sensor.async_write_ha_state.assert_called_once()

def test_grid_reward_reason_sensor(mock_api, entry_id):
    sensor = GridRewardReasonSensor(mock_api, entry_id)
    sensor.async_write_ha_state = MagicMock()
    assert sensor.name == "Grid Reward Reason"
    assert sensor.unique_id == f"{entry_id}_grid_reward_reason"
    sensor.update_data({"state": {"reasons": ["reason1", "reason2"]}})
    assert sensor.state == "reason1, reason2"
    sensor.async_write_ha_state.assert_called_once()

def test_grid_reward_current_month_sensor(mock_api, entry_id):
    sensor = GridRewardCurrentMonthSensor(mock_api, entry_id)
    sensor.async_write_ha_state = MagicMock()
    assert sensor.name == "Grid Reward Current Month"
    assert sensor.unique_id == f"{entry_id}_grid_reward_current_month"
    sensor.update_data({"rewardCurrentMonth": 100, "rewardCurrency": "EUR"})
    assert sensor.state == 100
    assert sensor.unit_of_measurement == "EUR"
    sensor.async_write_ha_state.assert_called_once()

def test_grid_reward_current_day_sensor(mock_api, entry_id):
    mock_tracker = MagicMock()
    mock_tracker.daily_reward = 10.5
    sensor = GridRewardCurrentDaySensor(mock_api, entry_id, mock_tracker)
    sensor.async_write_ha_state = MagicMock()
    assert sensor.name == "Grid Reward Current Day"
    assert sensor.unique_id == f"{entry_id}_grid_reward_current_day"
    sensor.update_data({"rewardCurrency": "EUR"})
    assert sensor.state == 10.5
    assert sensor.unit_of_measurement == "EUR"
    sensor.async_write_ha_state.assert_called_once()

def test_flex_device_state_sensor(mock_api, entry_id):
    device = {"id": "vehicle1", "type": "vehicle", "name": "My Car"}
    sensor = FlexDeviceStateSensor(mock_api, entry_id, device)
    sensor.async_write_ha_state = MagicMock()
    assert sensor.name == "My Car State"
    assert sensor.unique_id == "vehicle1_state"
    sensor.update_data(
        {
            "flexDevices": [
                {"vehicleId": "vehicle1", "state": {"__typename": "PluggedIn"}}
            ]
        }
    )
    assert sensor.state == "PluggedIn"
    sensor.async_write_ha_state.assert_called_once()

def test_flex_device_connectivity_sensor(mock_api, entry_id):
    device = {"id": "vehicle1", "type": "vehicle", "name": "My Car"}
    sensor = FlexDeviceConnectivitySensor(mock_api, entry_id, device)
    sensor.async_write_ha_state = MagicMock()
    assert sensor.name == "My Car Connectivity"
    assert sensor.unique_id == "vehicle1_connectivity"
    sensor.update_data({"flexDevices": [{"vehicleId": "vehicle1", "isPluggedIn": True}]})
    assert sensor.state == "Plugged In"
    sensor.async_write_ha_state.assert_called_once()