from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tibber_grid_reward.binary_sensor import (
    GRID_REWARD_ACTIVE_SENSOR_DESCRIPTION,
    FlexDeviceGridRewardActiveSensor,
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


@pytest.mark.parametrize("device_type", ["vehicle", "battery"])
def test_flex_device_binary_sensor_initial_state_unknown(device_type):
    """A device has no known reward status before its first snapshot."""
    sensor = FlexDeviceGridRewardActiveSensor(
        MagicMock(),
        "entry1",
        {"id": "device1", "type": device_type, "name": "Device"},
        GRID_REWARD_ACTIVE_SENSOR_DESCRIPTION,
    )

    assert sensor.is_on is None


@pytest.mark.parametrize(
    "device_type, id_key", [("vehicle", "vehicleId"), ("battery", "batteryId")]
)
@pytest.mark.parametrize(
    "payload",
    [
        {
            "flexDevices": [
                {"batteryId": "other", "state": {"__typename": "GridRewardAvailable"}}
            ]
        },
        {"flexDevices": []},
        {"flexDevices": None},
        {},
    ],
)
def test_flex_device_binary_sensor_missing_device_unknown(device_type, id_key, payload):
    """A missing device must lose its previous active status and reason."""
    sensor = FlexDeviceGridRewardActiveSensor(
        MagicMock(),
        "entry1",
        {"id": "device1", "type": device_type, "name": "Device"},
        GRID_REWARD_ACTIVE_SENSOR_DESCRIPTION,
    )
    sensor.update_data(
        {
            "flexDevices": [
                {
                    id_key: "device1",
                    "state": {"__typename": "GridRewardDelivering", "reason": "excess"},
                }
            ]
        }
    )
    assert sensor.is_on is True

    sensor.update_data(payload)

    assert sensor.is_on is None
    assert sensor.extra_state_attributes == {}


@pytest.mark.parametrize(
    "device_type, id_key", [("vehicle", "vehicleId"), ("battery", "batteryId")]
)
@pytest.mark.parametrize("state_fields", [{}, {"state": None}, {"state": {}}])
def test_flex_device_binary_sensor_missing_state_unknown(
    device_type, id_key, state_fields
):
    """A listed device without a status is unknown rather than inactive."""
    sensor = FlexDeviceGridRewardActiveSensor(
        MagicMock(),
        "entry1",
        {"id": "device1", "type": device_type, "name": "Device"},
        GRID_REWARD_ACTIVE_SENSOR_DESCRIPTION,
    )
    sensor.update_data(
        {
            "flexDevices": [
                {
                    id_key: "device1",
                    "state": {"__typename": "GridRewardDelivering", "reason": "excess"},
                }
            ]
        }
    )

    sensor.update_data({"flexDevices": [{id_key: "device1", **state_fields}]})

    assert sensor.is_on is None
    assert sensor.extra_state_attributes == {}


@pytest.mark.parametrize(
    "device_type, id_key", [("vehicle", "vehicleId"), ("battery", "batteryId")]
)
@pytest.mark.parametrize(
    "returned_state, expected_state",
    [("GridRewardDelivering", STATE_ON), ("GridRewardAvailable", STATE_OFF)],
)
async def test_missing_flex_device_preserved_in_home_assistant(
    hass, device_type, id_key, returned_state, expected_state
):
    """Snapshots update HA to unknown while retaining registry identity."""
    device = {"id": "device1", "type": device_type, "name": "Tribe 1"}
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "password",
            "home_id": "home1",
            "flex_devices": [device],
        },
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.tibber_grid_reward.PLATFORMS", ["binary_sensor"]),
        patch(
            "custom_components.tibber_grid_reward.TibberAPI.get_homes",
            AsyncMock(return_value=[{"id": "home1"}]),
        ),
        patch(
            "custom_components.tibber_grid_reward.TibberAPI.run_multiplexed_subscription",
            AsyncMock(),
        ),
        patch(
            "custom_components.tibber_grid_reward.DailyRewardTracker.async_setup",
            AsyncMock(),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        api = hass.data[DOMAIN][entry.entry_id]["api"]
        entity_registry = er.async_get(hass)
        device_registry = dr.async_get(hass)
        entity_id = entity_registry.async_get_entity_id(
            "binary_sensor", DOMAIN, "device1_grid_reward_active"
        )
        registered_entity = entity_registry.async_get(entity_id)
        registered_device = device_registry.async_get(registered_entity.device_id)

        def push_snapshot(devices):
            api._dispatch_grid_reward(
                {
                    "homeId": "home1",
                    "state": {"__typename": "GridRewardAvailable"},
                    "flexDevices": devices,
                }
            )

        push_snapshot(
            [
                {
                    id_key: "device1",
                    "state": {"__typename": "GridRewardDelivering", "reason": "excess"},
                }
            ]
        )
        assert hass.states.get(entity_id).state == STATE_ON

        # The log keeps Solis in the snapshot when Tribe 1 disappears.
        push_snapshot(
            [{"batteryId": "other", "state": {"__typename": "GridRewardAvailable"}}]
        )
        assert hass.states.get(entity_id).state == STATE_UNKNOWN
        assert "state" not in hass.states.get(entity_id).attributes
        assert "reason" not in hass.states.get(entity_id).attributes
        assert entity_registry.async_get(entity_id).id == registered_entity.id
        assert device_registry.async_get(registered_device.id) is not None
        assert entry.data["flex_devices"] == [device]

        push_snapshot([{id_key: "device1", "state": {"__typename": returned_state}}])
        assert hass.states.get(entity_id).state == expected_state
        assert entity_registry.async_get(entity_id).device_id == registered_device.id

        assert await hass.config_entries.async_unload(entry.entry_id)


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
