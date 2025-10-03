import pytest
from unittest.mock import MagicMock, patch
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from custom_components.tibber_grid_reward.const import DOMAIN
from custom_components.tibber_grid_reward.sensor import (
    async_setup_entry,
    PriceSensor,
)

@pytest.fixture
def mock_hass():
    """Mock HomeAssistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {DOMAIN: {}}
    return hass

@pytest.fixture
def mock_config_entry():
    """Mock ConfigEntry instance."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry_id"
    entry.data = {
        "home_id": "test_home_id",
        "api_key": "test_api_key",
        "flex_devices": [],
    }
    entry.options = {}
    return entry

@patch("custom_components.tibber_grid_reward.sensor.TibberPublicAPI")
async def test_price_sensor_isolation(
    mock_public_api, mock_hass, mock_config_entry
):
    """Test that PriceSensor is not added to grid_reward_devices."""
    mock_tibber_api = MagicMock()
    mock_hass.data[DOMAIN][mock_config_entry.entry_id] = {
        "api": mock_tibber_api,
        "public_api": mock_public_api,
        "flex_devices": [],
        "grid_reward_devices": [],
        "daily_tracker": MagicMock(),
        "session_tracker": MagicMock(),
    }

    async_add_entities = MagicMock()

    await async_setup_entry(mock_hass, mock_config_entry, async_add_entities)

    grid_reward_devices = mock_hass.data[DOMAIN][mock_config_entry.entry_id][
        "grid_reward_devices"
    ]
    
    assert not any(
        isinstance(device, PriceSensor) for device in grid_reward_devices
    ), "PriceSensor should not be in grid_reward_devices"

    added_entities = async_add_entities.call_args[0][0]
    assert any(
        isinstance(entity, PriceSensor) for entity in added_entities
    ), "PriceSensor should be added to entities"