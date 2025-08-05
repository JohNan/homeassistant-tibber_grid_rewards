from unittest.mock import MagicMock, AsyncMock
import datetime
import pytest

from custom_components.tibber_grid_reward.time import DepartureTimeEntity
from custom_components.tibber_grid_reward.const import DOMAIN

@pytest.fixture
def mock_api():
    api = MagicMock()
    api.set_departure_time = AsyncMock()
    return api

@pytest.fixture
def device():
    return {"id": "vehicle1", "type": "vehicle", "name": "My Car"}

@pytest.fixture
def sensor(mock_api, device):
    sensor = DepartureTimeEntity(mock_api, "test_entry_id", device, 0)
    sensor.async_write_ha_state = MagicMock()
    return sensor

def test_initial_state(sensor):
    assert sensor.name == "My Car Departure Time Monday"
    assert sensor.unique_id == "vehicle1_departure_time_monday"
    assert sensor.native_value is None

def test_device_info(sensor):
    assert sensor.device_info == {
        "identifiers": {(DOMAIN, "vehicle1")},
    }

def test_update_data(sensor):
    sensor.update_data(
        {
            "userSettings": [
                {
                    "key": "online.vehicle.smartCharging.departureTimes.monday",
                    "value": "08:00",
                }
            ]
        }
    )
    assert sensor.native_value == datetime.time(8, 0)
    sensor.async_write_ha_state.assert_called_once()

async def test_async_set_value(sensor, mock_api):
    await sensor.async_set_value(datetime.time(9, 30))
    mock_api.set_departure_time.assert_called_once_with(
        home_id=mock_api.home_id,
        vehicle_id="vehicle1",
        day="monday",
        time_str="09:30",
    )
    assert sensor.native_value == datetime.time(9, 30)
    sensor.async_write_ha_state.assert_called_once()