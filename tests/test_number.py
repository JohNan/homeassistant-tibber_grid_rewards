from unittest.mock import MagicMock, AsyncMock
import pytest

from custom_components.tibber_grid_reward.number import BatteryLevelEntity
from custom_components.tibber_grid_reward.const import DOMAIN

@pytest.fixture
def mock_api():
    api = MagicMock()
    api.set_battery_level = AsyncMock()
    return api

@pytest.fixture
def device():
    return {"id": "vehicle1", "type": "vehicle", "name": "My Car"}

@pytest.fixture
def entity(mock_api, device):
    entity = BatteryLevelEntity(mock_api, "test_entry_id", device)
    entity.async_write_ha_state = MagicMock()
    return entity

def test_initial_state(entity):
    assert entity.name == "My Car Battery Level"
    assert entity.unique_id == "vehicle1_battery_level"
    assert entity.native_value is None
    assert entity.available is False

def test_device_info(entity):
    assert entity.device_info == {
        "identifiers": {(DOMAIN, "vehicle1")},
    }

def test_update_data_offline_vehicle(entity):
    """Offline vehicles (isAlive: false) report battery.level directly."""
    entity.update_data({"isAlive": False, "battery": {"level": 77}})
    assert entity.native_value == 77
    assert entity.available is True
    entity.async_write_ha_state.assert_called_once()

def test_update_data_online_vehicle_stays_unavailable(entity):
    """Online vehicles (isAlive: true) are out of scope for this entity."""
    entity.update_data({"isAlive": True, "battery": {"level": 55}})
    assert entity.native_value is None
    assert entity.available is False
    entity.async_write_ha_state.assert_called_once()

def test_update_data_unknown_kind_stays_unavailable(entity):
    """No isAlive info yet: default to unavailable, not a guess."""
    entity.update_data({"battery": {"level": 55}})
    assert entity.native_value is None
    assert entity.available is False

def test_update_data_missing_battery_field(entity):
    """battery may come back null/missing: handle gracefully, no crash."""
    entity.update_data({"isAlive": False})
    assert entity.native_value is None
    assert entity.available is True

def test_update_data_online_after_offline_clears_value(entity):
    """A vehicle later reporting isAlive: true clears any stale value."""
    entity.update_data({"isAlive": False, "battery": {"level": 40}})
    assert entity.native_value == 40
    entity.update_data({"isAlive": True, "battery": {"level": 40}})
    assert entity.native_value is None
    assert entity.available is False

async def test_async_set_native_value_offline(entity, mock_api):
    entity.update_data({"isAlive": False, "battery": {"level": 40}})
    await entity.async_set_native_value(60)
    mock_api.set_battery_level.assert_called_once_with(
        home_id=mock_api.home_id,
        vehicle_id="vehicle1",
        level=60,
    )
    assert entity.native_value == 60

async def test_async_set_native_value_ignored_when_unavailable(entity, mock_api):
    """Guard against writing for a vehicle never confirmed offline."""
    await entity.async_set_native_value(60)
    mock_api.set_battery_level.assert_not_called()
    assert entity.native_value is None
