from unittest.mock import MagicMock, AsyncMock
import pytest

from custom_components.tibber_grid_reward.number import (
    BatteryLevelEntity,
    _BatteryLevelEntityManager,
)
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
def vehicle_devices():
    return []

@pytest.fixture
def async_add_entities():
    return MagicMock()

@pytest.fixture
def manager(mock_api, device, vehicle_devices, async_add_entities):
    manager = _BatteryLevelEntityManager(mock_api, "test_entry_id", device, vehicle_devices, async_add_entities)
    vehicle_devices.append(manager)
    return manager

# --- _BatteryLevelEntityManager ---

def test_manager_waits_when_kind_unknown(manager, vehicle_devices, async_add_entities):
    """No isAlive in the payload yet: manager stays in place, nothing added."""
    manager.update_data({})
    assert manager in vehicle_devices
    async_add_entities.assert_not_called()

def test_manager_confirmed_online_adds_nothing(manager, vehicle_devices, async_add_entities):
    manager.update_data({"isAlive": True, "battery": {"level": None}})
    assert manager not in vehicle_devices
    assert vehicle_devices == []
    async_add_entities.assert_not_called()

def test_manager_confirmed_offline_adds_entity(manager, vehicle_devices, async_add_entities, mock_api):
    manager.update_data({"isAlive": False, "battery": {"level": 77}})
    assert manager not in vehicle_devices
    assert len(vehicle_devices) == 1
    entity = vehicle_devices[0]
    assert isinstance(entity, BatteryLevelEntity)
    assert entity.native_value == 77
    assert entity.available is True
    async_add_entities.assert_called_once_with([entity])

def test_manager_resolves_only_once(manager, vehicle_devices, async_add_entities):
    """A second update after resolution is a no-op (manager already removed itself)."""
    manager.update_data({"isAlive": False, "battery": {"level": 77}})
    async_add_entities.reset_mock()
    manager.update_data({"isAlive": False, "battery": {"level": 50}})
    async_add_entities.assert_not_called()
    assert len(vehicle_devices) == 1  # still just the one entity added earlier

# --- BatteryLevelEntity ---

@pytest.fixture
def entity(mock_api, device):
    entity = BatteryLevelEntity(mock_api, "test_entry_id", device, {"isAlive": False, "battery": {"level": 40}})
    entity.async_write_ha_state = MagicMock()
    return entity

def test_initial_state(entity):
    assert entity.name == "My Car Battery Level"
    assert entity.unique_id == "vehicle1_battery_level"
    assert entity.native_value == 40
    assert entity.available is True

def test_device_info(entity):
    assert entity.device_info == {
        "identifiers": {(DOMAIN, "vehicle1")},
    }

def test_update_data_offline_vehicle(entity):
    entity.update_data({"isAlive": False, "battery": {"level": 77}})
    assert entity.native_value == 77
    assert entity.available is True
    entity.async_write_ha_state.assert_called_once()

def test_update_data_missing_battery_field(entity):
    """battery may come back null/missing: handle gracefully, no crash."""
    entity.update_data({"isAlive": False})
    assert entity.native_value is None
    assert entity.available is True

def test_update_data_vehicle_later_reports_online(entity):
    """Defensive: if a vehicle created as offline later reports isAlive:
    true, the entity should stop claiming to have a meaningful value."""
    entity.update_data({"isAlive": True, "battery": {"level": 40}})
    assert entity.native_value is None
    assert entity.available is False

async def test_async_set_native_value(entity, mock_api):
    await entity.async_set_native_value(60)
    mock_api.set_battery_level.assert_called_once_with(
        home_id=mock_api.home_id,
        vehicle_id="vehicle1",
        level=60,
    )
    assert entity.native_value == 60

async def test_async_set_native_value_ignored_when_unavailable(entity, mock_api):
    """Guard against writing once a vehicle has flipped to online."""
    entity.update_data({"isAlive": True, "battery": {"level": 40}})
    await entity.async_set_native_value(60)
    mock_api.set_battery_level.assert_not_called()
