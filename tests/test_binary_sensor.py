from unittest.mock import MagicMock
import pytest

from custom_components.tibber_grid_reward.binary_sensor import GridRewardActiveSensor
from custom_components.tibber_grid_reward.const import DOMAIN

@pytest.fixture
def sensor():
    mock_api = MagicMock()
    sensor = GridRewardActiveSensor(mock_api, "test_entry_id")
    sensor.async_write_ha_state = MagicMock()
    return sensor

def test_initial_state(sensor):
    assert not sensor.is_on
    assert sensor.name == "Grid Reward Active"
    assert sensor.unique_id == "test_entry_id_grid_reward_active"

def test_device_info(sensor):
    assert sensor.device_info == {
        "identifiers": {(DOMAIN, "test_entry_id")},
        "name": "Tibber Grid Reward",
        "manufacturer": "Tibber",
    }

def test_update_data(sensor):
    sensor.update_data({"state": {"__typename": "GridRewardDelivering"}})
    assert sensor.is_on
    sensor.async_write_ha_state.assert_called_once()

    sensor.update_data({"state": {"__typename": "GridRewardAvailable"}})
    assert not sensor.is_on
    assert sensor.async_write_ha_state.call_count == 2