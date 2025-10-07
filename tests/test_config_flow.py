import pytest
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_PASSWORD, CONF_API_KEY
from homeassistant.data_entry_flow import FlowResultType

from custom_components.tibber_grid_reward.const import DOMAIN
from custom_components.tibber_grid_reward.client import TibberAuthError

from pytest_homeassistant_custom_component.common import MockConfigEntry

# Mock data
MOCK_USERNAME = "test@example.com"
MOCK_PASSWORD = "test_password"
MOCK_API_KEY = "test_api_key"
MOCK_HOME_ID = "home1"

MOCK_CONFIG_DATA = {
    "username": MOCK_USERNAME,
    "password": MOCK_PASSWORD,
    "api_key": MOCK_API_KEY,
    "home_id": MOCK_HOME_ID,
    "flex_devices": [{"id": "flex1", "type": "vehicle", "name": "Car 1"}],
}

MOCK_HOMES = [{"id": MOCK_HOME_ID, "title": "My Home"}]
MOCK_FLEX_DEVICES = {
    "flex1": {"type": "vehicle", "name": "Car 1"},
    "flex2": {"type": "battery", "name": "Battery"},
}

@pytest.fixture(name="mock_tibber_api")
def mock_tibber_api_fixture():
    """Mock the TibberAPI client."""
    with patch("custom_components.tibber_grid_reward.config_flow.TibberAPI") as mock_api:
        instance = mock_api.return_value
        instance.get_homes = AsyncMock(return_value=MOCK_HOMES)
        instance.validate_grid_reward = AsyncMock(return_value={"flexDevices": [
            {"__typename": "GridRewardVehicle", "vehicleId": "flex1", "shortName": "Car 1"},
            {"__typename": "GridRewardBattery", "batteryId": "flex2", "shortName": "Battery"},
        ]})
        yield mock_api

@pytest.fixture(name="mock_tibber_public_api")
def mock_tibber_public_api_fixture():
    """Mock the TibberPublicAPI client."""
    with patch("custom_components.tibber_grid_reward.config_flow.TibberPublicAPI") as mock_public_api:
        public_instance = mock_public_api.return_value
        public_instance.get_homes = AsyncMock(return_value=MOCK_HOMES)
        yield mock_public_api


async def test_reauth_flow_success(hass: HomeAssistant, mock_tibber_api, mock_tibber_public_api):
    """Test the reauthentication flow succeeds with valid credentials."""
    mock_entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG_DATA)
    mock_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reauth", "entry_id": mock_entry.entry_id}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth"

    # Simulate user providing new credentials
    new_password = "new_password"
    new_api_key = "new_api_key"

    with patch("custom_components.tibber_grid_reward.async_setup_entry", return_value=True) as mock_setup_entry:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_PASSWORD: new_password,
                CONF_API_KEY: new_api_key,
            },
        )

    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "reauth_successful"

    assert mock_entry.data["password"] == new_password
    assert mock_entry.data["api_key"] == new_api_key
    assert len(mock_setup_entry.mock_calls) == 1

async def test_reauth_flow_invalid_creds(hass: HomeAssistant, mock_tibber_api, mock_tibber_public_api):
    """Test the reauthentication flow fails with invalid credentials."""
    mock_entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG_DATA)
    mock_entry.add_to_hass(hass)

    mock_tibber_api.return_value.get_homes.side_effect = TibberAuthError

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reauth", "entry_id": mock_entry.entry_id}
    )

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_PASSWORD: "wrong_password",
            CONF_API_KEY: "wrong_key",
        },
    )

    assert result2["type"] == FlowResultType.FORM
    assert result2["step_id"] == "reauth"
    assert result2["errors"] == {"base": "auth"}

async def test_reconfigure_flow(hass: HomeAssistant, mock_tibber_api, mock_tibber_public_api):
    """Test the reconfiguration flow to update flex devices."""
    mock_entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG_DATA)
    mock_entry.add_to_hass(hass)

    with patch("custom_components.tibber_grid_reward.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "reconfigure", "entry_id": mock_entry.entry_id}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    # Check that current device is pre-selected
    key = next(k for k in result["data_schema"].schema if k.schema == "flex_devices")
    assert key.default() == ["flex1"]

    # Simulate user selecting a different set of devices
    with patch("custom_components.tibber_grid_reward.async_setup_entry", return_value=True) as mock_setup_entry:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"flex_devices": ["flex2"]},
        )

    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "reconfigure_successful"

    assert len(mock_entry.data["flex_devices"]) == 1
    assert mock_entry.data["flex_devices"][0]["id"] == "flex2"
    assert mock_entry.data["flex_devices"][0]["name"] == "Battery"
    assert len(mock_setup_entry.mock_calls) == 1