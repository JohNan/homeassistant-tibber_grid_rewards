from unittest.mock import MagicMock

import pytest

from custom_components.tibber_grid_reward.binary_sensor import (
    GRID_REWARD_ACTIVE_SENSOR_DESCRIPTION,
    GridRewardActiveSensor,
)
from custom_components.tibber_grid_reward.const import DOMAIN


@pytest.fixture
def sensor():
    """Fixture for a GridRewardActiveSensor."""
    mock_api = MagicMock()
    sensor = GridRewardActiveSensor(
        mock_api, "test_entry_id", GRID_REWARD_ACTIVE_SENSOR_DESCRIPTION
    )
    sensor.hass = MagicMock()
    sensor.async_write_ha_state = MagicMock()
    return sensor


def test_initial_state(sensor):
    """Test the initial state of the sensor."""
    assert not sensor.is_on
    assert sensor.name == "Grid Reward Active"
    assert sensor.unique_id == "test_entry_id_grid_reward_active"


def test_device_info(sensor):
    """Test the device info of the sensor."""
    assert sensor.device_info == {
        "identifiers": {(DOMAIN, "test_entry_id")},
        "name": "Tibber Grid Reward",
        "manufacturer": "Tibber",
    }


def test_update_data(sensor):
    """Test the update_data method of the sensor."""
    sensor.update_data({"state": {"__typename": "GridRewardDelivering"}})
    assert sensor.is_on
    sensor.async_write_ha_state.assert_called_once()

    sensor.update_data({"state": {"__typename": "GridRewardAvailable"}})
    assert not sensor.is_on
    assert sensor.async_write_ha_state.call_count == 2


def test_update_data_no_hass():
    """Test update_data when self.hass is None does not raise RuntimeError."""
    mock_api = MagicMock()
    sensor_obj = GridRewardActiveSensor(
        mock_api, "test_entry_id", GRID_REWARD_ACTIVE_SENSOR_DESCRIPTION
    )
    assert sensor_obj.hass is None

    sensor_obj.update_data({"state": {"__typename": "GridRewardDelivering"}})
    assert sensor_obj.is_on


def test_flex_device_binary_sensor_vehicle():
    """Test FlexDeviceGridRewardActiveSensor for a vehicle."""
    from custom_components.tibber_grid_reward.binary_sensor import (
        FlexDeviceGridRewardActiveSensor,
    )

    mock_api = MagicMock()
    device = {"id": "car1", "type": "vehicle", "name": "Model 3"}
    sensor = FlexDeviceGridRewardActiveSensor(
        mock_api, "entry1", device, GRID_REWARD_ACTIVE_SENSOR_DESCRIPTION
    )
    sensor.hass = MagicMock()
    sensor.async_write_ha_state = MagicMock()

    assert not sensor.is_on
    assert sensor.name == "Model 3 Grid Reward Active"
    assert sensor.unique_id == "car1_grid_reward_active"
    assert sensor.device_info == {
        "identifiers": {(DOMAIN, "car1")},
        "name": "Model 3",
        "manufacturer": "Tibber",
        "via_device": (DOMAIN, "entry1"),
    }

    # Simulate delivering push
    payload = {
        "flexDevices": [
            {
                "vehicleId": "car1",
                "state": {
                    "__typename": "GridRewardDelivering",
                    "reason": "Smart charging",
                },
            }
        ]
    }
    sensor.update_data(payload)
    assert sensor.is_on
    assert sensor.extra_state_attributes == {
        "state": "GridRewardDelivering",
        "reason": "Smart charging",
    }
    sensor.async_write_ha_state.assert_called_once()

    # Simulate unavailable push
    payload2 = {
        "flexDevices": [
            {
                "vehicleId": "car1",
                "state": {
                    "__typename": "GridRewardUnavailable",
                    "reasons": ["UNPLUGGED"],
                },
            }
        ]
    }
    sensor.update_data(payload2)
    assert not sensor.is_on
    assert sensor.extra_state_attributes == {
        "state": "GridRewardUnavailable",
        "reasons": ["UNPLUGGED"],
    }


def test_flex_device_binary_sensor_battery():
    """Test FlexDeviceGridRewardActiveSensor for a battery."""
    from custom_components.tibber_grid_reward.binary_sensor import (
        FlexDeviceGridRewardActiveSensor,
    )

    mock_api = MagicMock()
    device = {"id": "bat1", "type": "battery", "name": "Homevolt"}
    sensor = FlexDeviceGridRewardActiveSensor(
        mock_api, "entry1", device, GRID_REWARD_ACTIVE_SENSOR_DESCRIPTION
    )
    sensor.hass = MagicMock()
    sensor.async_write_ha_state = MagicMock()

    payload = {
        "flexDevices": [
            {
                "batteryId": "bat1",
                "state": {
                    "__typename": "GridRewardDelivering",
                    "reason": "Discharging for rewards",
                },
            }
        ]
    }
    sensor.update_data(payload)
    assert sensor.is_on
    assert sensor.extra_state_attributes["state"] == "GridRewardDelivering"


async def test_binary_sensor_async_setup_entry_multiple_devices():
    """Test setup with both home and flex device binary sensors."""
    from custom_components.tibber_grid_reward.binary_sensor import (
        FlexDeviceGridRewardActiveSensor,
        async_setup_entry,
    )

    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_entry"
    mock_api = MagicMock()
    devices = [
        {"id": "car1", "type": "vehicle", "name": "EV"},
        {"id": "bat1", "type": "battery", "name": "Battery"},
    ]
    grid_reward_devices = []
    hass.data = {
        DOMAIN: {
            "test_entry": {
                "api": mock_api,
                "flex_devices": devices,
                "grid_reward_devices": grid_reward_devices,
            }
        }
    }
    async_add_entities = MagicMock()

    await async_setup_entry(hass, entry, async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args[0][0]
    # 1 home-level sensor + 2 flex device sensors = 3 sensors
    assert len(entities) == 3
    assert isinstance(entities[0], GridRewardActiveSensor)
    assert isinstance(entities[1], FlexDeviceGridRewardActiveSensor)
    assert isinstance(entities[2], FlexDeviceGridRewardActiveSensor)
    assert len(grid_reward_devices) == 3
