"""Tests for the Tibber Grid Reward switch platform."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.tibber_grid_reward.const import DOMAIN
from custom_components.tibber_grid_reward.switch import (
    SmartChargingSwitch,
    async_setup_entry,
)


@pytest.fixture
def mock_api():
    api = MagicMock()
    api.home_id = "test_home_id"
    api.set_smart_charging_enabled = AsyncMock()
    return api


@pytest.fixture
def device():
    return {"id": "vehicle1", "type": "vehicle", "name": "My Car"}


@pytest.fixture
def switch_entity(mock_api, device):
    switch = SmartChargingSwitch(mock_api, "test_entry_id", device)
    switch.async_write_ha_state = MagicMock()
    return switch


def test_switch_initial_state(switch_entity):
    assert switch_entity.name == "My Car Smart Charging"
    assert switch_entity.unique_id == "vehicle1_smart_charging_switch"
    assert switch_entity.is_on is None
    assert switch_entity.icon == "mdi:ev-station"


def test_switch_device_info(switch_entity):
    assert switch_entity.device_info == {
        "identifiers": {(DOMAIN, "vehicle1")},
        "name": "My Car",
        "manufacturer": "Tibber",
        "via_device": (DOMAIN, "test_entry_id"),
    }


def test_update_data_from_grid_reward(switch_entity):
    switch_entity.update_data(
        {
            "flexDevices": [
                {
                    "vehicleId": "vehicle1",
                    "isSmartChargingEnabled": True,
                }
            ]
        }
    )
    assert switch_entity.is_on is True
    switch_entity.async_write_ha_state.assert_called_once()


def test_update_data_from_user_settings(switch_entity):
    switch_entity.update_data(
        {
            "userSettings": [
                {
                    "key": "online.vehicle.smartCharging.enabled",
                    "value": "false",
                }
            ]
        }
    )
    assert switch_entity.is_on is False
    switch_entity.async_write_ha_state.assert_called_once()


def test_update_data_from_smart_charging_status(switch_entity):
    switch_entity.update_data({"smartChargingStatus": "enabled"})
    assert switch_entity.is_on is True
    switch_entity.async_write_ha_state.assert_called_once()

    switch_entity.async_write_ha_state.reset_mock()
    switch_entity.update_data({"smartChargingStatus": "suspended"})
    assert switch_entity.is_on is True
    switch_entity.async_write_ha_state.assert_called_once()


async def test_async_turn_on(switch_entity, mock_api):
    await switch_entity.async_turn_on()
    mock_api.set_smart_charging_enabled.assert_called_once_with(
        home_id="test_home_id",
        vehicle_id="vehicle1",
        enabled=True,
    )
    assert switch_entity.is_on is True
    switch_entity.async_write_ha_state.assert_called_once()


async def test_async_turn_off(switch_entity, mock_api):
    await switch_entity.async_turn_off()
    mock_api.set_smart_charging_enabled.assert_called_once_with(
        home_id="test_home_id",
        vehicle_id="vehicle1",
        enabled=False,
    )
    assert switch_entity.is_on is False
    switch_entity.async_write_ha_state.assert_called_once()


async def test_async_setup_entry(mock_api, device):
    hass = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"

    hass.data = {
        DOMAIN: {
            "test_entry": {
                "api": mock_api,
                "flex_devices": [device, {"id": "battery1", "type": "battery", "name": "Battery"}],
                "grid_reward_devices": [],
                "vehicle_devices": {"vehicle1": []},
            }
        }
    }

    async_add_entities = MagicMock()
    await async_setup_entry(hass, config_entry, async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args[0][0]
    assert len(entities) == 1
    assert isinstance(entities[0], SmartChargingSwitch)
    assert entities[0] in hass.data[DOMAIN]["test_entry"]["grid_reward_devices"]
    assert entities[0] in hass.data[DOMAIN]["test_entry"]["vehicle_devices"]["vehicle1"]
