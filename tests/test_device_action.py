"""Tests for device actions."""
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

from custom_components.tibber_grid_reward.const import DOMAIN
from custom_components.tibber_grid_reward.device_action import (
    async_call_action_from_config,
    async_get_action_capabilities,
    async_get_actions,
)


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


async def test_async_get_actions(mock_hass):
    mock_entry = MagicMock()
    mock_entry.domain = "time"
    mock_entry.platform = DOMAIN
    mock_entry.entity_id = "time.my_car_departure_time_monday"

    mock_registry = MagicMock()
    mock_registry.devices = {}
    
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "homeassistant.helpers.entity_registry.async_get",
            lambda hass: mock_registry,
        )
        mp.setattr(
            "homeassistant.helpers.entity_registry.async_entries_for_device",
            lambda reg, dev_id: [mock_entry],
        )
        actions = await async_get_actions(mock_hass, "device123")
        assert len(actions) == 1
        assert actions[0] == {
            "device_id": "device123",
            "domain": DOMAIN,
            "entity_id": "time.my_car_departure_time_monday",
            "type": "set_value",
        }


async def test_async_get_action_capabilities(mock_hass):
    caps = await async_get_action_capabilities(mock_hass, {"type": "set_value"})
    assert "extra_fields" in caps
    assert isinstance(caps["extra_fields"], vol.Schema)

    empty_caps = await async_get_action_capabilities(mock_hass, {"type": "unknown"})
    assert empty_caps == {}


async def test_async_call_action_from_config(mock_hass):
    config = {
        "device_id": "device123",
        "domain": DOMAIN,
        "entity_id": "time.my_car_departure_time_monday",
        "type": "set_value",
    }
    variables = {"time": "08:00:00"}
    await async_call_action_from_config(mock_hass, config, variables, None)

    mock_hass.services.async_call.assert_called_once_with(
        "time",
        "set_value",
        {
            "entity_id": "time.my_car_departure_time_monday",
            "time": "08:00:00",
        },
        blocking=True,
        context=None,
    )
