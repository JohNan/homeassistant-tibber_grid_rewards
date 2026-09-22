from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_API_KEY, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tibber_grid_reward.client import TibberAuthError
from custom_components.tibber_grid_reward.const import DOMAIN

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
    with patch(
        "custom_components.tibber_grid_reward.config_flow.TibberAPI"
    ) as mock_api:
        instance = mock_api.return_value
        instance.get_homes = AsyncMock(return_value=MOCK_HOMES)
        instance.validate_grid_reward = AsyncMock(
            return_value={
                "flexDevices": [
                    {
                        "__typename": "GridRewardVehicle",
                        "vehicleId": "flex1",
                        "shortName": "Car 1",
                    },
                    {
                        "__typename": "GridRewardBattery",
                        "batteryId": "flex2",
                        "shortName": "Battery",
                    },
                ]
            }
        )
        yield mock_api


@pytest.fixture(name="mock_tibber_public_api")
def mock_tibber_public_api_fixture():
    """Mock the TibberPublicAPI client."""
    with patch(
        "custom_components.tibber_grid_reward.config_flow.TibberPublicAPI"
    ) as mock_public_api:
        public_instance = mock_public_api.return_value
        public_instance.get_homes = AsyncMock(return_value=MOCK_HOMES)
        yield mock_public_api


async def test_reauth_flow_success(
    hass: HomeAssistant, mock_tibber_api, mock_tibber_public_api
):
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

    with patch(
        "custom_components.tibber_grid_reward.async_setup_entry", return_value=True
    ) as mock_setup_entry:
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


async def test_reauth_flow_invalid_creds(
    hass: HomeAssistant, mock_tibber_api, mock_tibber_public_api
):
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


async def test_reconfigure_flow(
    hass: HomeAssistant, mock_tibber_api, mock_tibber_public_api
):
    """Test the reconfiguration flow to update flex devices."""
    mock_entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG_DATA)
    mock_entry.add_to_hass(hass)

    with patch(
        "custom_components.tibber_grid_reward.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "reconfigure", "entry_id": mock_entry.entry_id}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    # Check that current device is pre-selected
    key = next(k for k in result["data_schema"].schema if k.schema == "flex_devices")
    assert key.default() == ["flex1"]

    # Simulate user selecting a different set of devices
    with patch(
        "custom_components.tibber_grid_reward.async_setup_entry", return_value=True
    ) as mock_setup_entry:
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


async def test_options_flow(hass: HomeAssistant, mock_tibber_public_api):
    """Test options flow initialization and completion."""
    mock_entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG_DATA,
        options={CONF_API_KEY: "old_key"},
    )
    mock_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_API_KEY: "new_api_key"},
    )

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["data"] == {CONF_API_KEY: "new_api_key"}


async def test_user_flow_multiple_homes(
    hass: HomeAssistant, mock_tibber_api, mock_tibber_public_api
):
    """Test user can configure a second home using the same account credentials."""
    # Existing entry for Home 1
    existing_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{MOCK_USERNAME}_{MOCK_HOME_ID}",
        data=MOCK_CONFIG_DATA,
    )
    existing_entry.add_to_hass(hass)

    # API returns both Home 1 and Home 2
    mock_tibber_api.return_value.get_homes.return_value = [
        {"id": MOCK_HOME_ID, "title": "Home 1"},
        {"id": "home2", "title": "Home 2"},
    ]
    mock_tibber_public_api.return_value.get_homes.return_value = [
        {"id": MOCK_HOME_ID, "title": "Home 1"},
        {"id": "home2", "title": "Home 2"},
    ]

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    # Submit credentials
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "username": MOCK_USERNAME,
            "password": MOCK_PASSWORD,
            "api_key": MOCK_API_KEY,
        },
    )

    # Home 1 is filtered out because it is already configured; Home 2 is presented
    assert result2["type"] == FlowResultType.FORM
    assert result2["step_id"] == "select_home"
    schema = result2["data_schema"].schema
    home_key = next(k for k in schema if k == "home_id")
    val = schema[home_key]
    assert "home2" in val.container
    assert MOCK_HOME_ID not in val.container

    # Select Home 2
    result3 = await hass.config_entries.flow.async_configure(
        result2["flow_id"],
        {"home_id": "home2"},
    )
    assert result3["type"] == FlowResultType.FORM
    assert result3["step_id"] == "select_devices"

    with patch(
        "custom_components.tibber_grid_reward.async_setup_entry", return_value=True
    ):
        result4 = await hass.config_entries.flow.async_configure(
            result3["flow_id"],
            {"flex_devices": ["flex1"]},
        )

    assert result4["type"] == FlowResultType.CREATE_ENTRY
    assert result4["title"] == "Home 2"
    assert result4["data"]["home_id"] == "home2"
    assert result4["result"].unique_id == f"{MOCK_USERNAME}_home2"


async def test_user_flow_all_homes_configured(
    hass: HomeAssistant, mock_tibber_api, mock_tibber_public_api
):
    """Test flow aborts with already_configured when all homes are already added."""
    existing_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{MOCK_USERNAME}_{MOCK_HOME_ID}",
        data=MOCK_CONFIG_DATA,
    )
    existing_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "username": MOCK_USERNAME,
            "password": MOCK_PASSWORD,
            "api_key": MOCK_API_KEY,
        },
    )
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


async def test_unique_id_migration(hass: HomeAssistant):
    """Test legacy unique_id (username) is migrated to home-scoped unique_id."""
    from custom_components.tibber_grid_reward import async_setup_entry

    legacy_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_USERNAME,
        data=MOCK_CONFIG_DATA,
    )
    legacy_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.tibber_grid_reward.TibberAPI.get_homes",
            AsyncMock(return_value=[{"id": MOCK_HOME_ID}]),
        ),
        patch(
            "custom_components.tibber_grid_reward.DailyRewardTracker.async_setup",
            AsyncMock(),
        ),
        patch(
            "custom_components.tibber_grid_reward.RewardSessionTracker.async_load",
            AsyncMock(),
        ),
        patch(
            "custom_components.tibber_grid_reward.TibberAPI.subscribe_grid_reward",
            AsyncMock(),
        ),
        patch(
            "custom_components.tibber_grid_reward.TibberAPI.subscribe_vehicle_state",
            AsyncMock(),
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            AsyncMock(),
        ),
    ):
        assert await async_setup_entry(hass, legacy_entry) is True

    assert legacy_entry.unique_id == f"{MOCK_USERNAME}_{MOCK_HOME_ID}"
