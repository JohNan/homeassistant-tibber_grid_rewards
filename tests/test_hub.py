"""Tests for TibberAccountHub and unified account lifecycle."""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tibber_grid_reward import async_setup_entry, async_unload_entry
from custom_components.tibber_grid_reward.client import TibberAPI
from custom_components.tibber_grid_reward.const import DOMAIN
from custom_components.tibber_grid_reward.hub import TibberAccountHub
from custom_components.tibber_grid_reward.public_client import TibberPublicAPI


@pytest.fixture
def mock_tibber_api() -> TibberAPI:
    """Return a mock TibberAPI client."""
    api = MagicMock(spec=TibberAPI)
    api.register_grid_reward_callback = MagicMock()
    api.unregister_grid_reward_callback = MagicMock()
    api.register_vehicle_callback = MagicMock()
    api.unregister_vehicle_callback = MagicMock()
    api.trigger_subscription_refresh = MagicMock()
    api.run_multiplexed_subscription = AsyncMock()
    api.async_close_websocket = AsyncMock()
    return api


@pytest.fixture
def mock_public_api() -> TibberPublicAPI:
    """Return a mock TibberPublicAPI client."""
    return MagicMock(spec=TibberPublicAPI)


def test_hub_active_targets(hass: HomeAssistant, mock_tibber_api: TibberAPI):
    """Test get_active_targets aggregates all homes and vehicles across entries."""
    hub = TibberAccountHub(hass, "user@test.com", mock_tibber_api)

    entry1 = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_1",
        data={
            "username": "user@test.com",
            "home_id": "home_1",
            "flex_devices": [
                {"id": "veh_1", "type": "vehicle"},
                {"id": "bat_1", "type": "battery"},
            ],
        },
    )
    entry2 = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_2",
        data={
            "username": "user@test.com",
            "home_id": "home_2",
            "flex_devices": [
                {"id": "veh_2", "type": "vehicle"},
            ],
        },
    )

    cb1 = MagicMock()
    veh_cb1 = {"veh_1": MagicMock()}
    hub.register_home(entry1, cb1, veh_cb1)

    cb2 = MagicMock()
    veh_cb2 = {"veh_2": MagicMock()}
    hub.register_home(entry2, cb2, veh_cb2)

    homes, vehicles = hub.get_active_targets()
    assert homes == {"home_1", "home_2"}
    assert vehicles == {"veh_1", "veh_2"}
    assert hub.has_entries() is True

    # Unregister home 1
    hub.unregister_home("entry_1")
    homes, vehicles = hub.get_active_targets()
    assert homes == {"home_2"}
    assert vehicles == {"veh_2"}
    assert hub.has_entries() is True

    # Unregister home 2
    hub.unregister_home("entry_2")
    homes, vehicles = hub.get_active_targets()
    assert homes == set()
    assert vehicles == set()
    assert hub.has_entries() is False


async def test_hub_websocket_lifecycle(hass: HomeAssistant, mock_tibber_api: TibberAPI):
    """Test that hub creates a single background task and cleans up properly on close."""
    hub = TibberAccountHub(hass, "user@test.com", mock_tibber_api)

    # Make run_multiplexed_subscription block until cancelled
    async def fake_ws_subscription(get_targets):
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.Event().wait()

    mock_tibber_api.run_multiplexed_subscription.side_effect = fake_ws_subscription

    entry1 = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_1",
        data={"username": "user@test.com", "home_id": "home_1", "flex_devices": []},
    )
    entry2 = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_2",
        data={"username": "user@test.com", "home_id": "home_2", "flex_devices": []},
    )

    hub.register_home(entry1, MagicMock(), {})
    first_task = hub._ws_task
    assert first_task is not None
    assert not first_task.done()

    # Registering second entry reuses the existing WebSocket task
    hub.register_home(entry2, MagicMock(), {})
    assert hub._ws_task is first_task
    assert mock_tibber_api.trigger_subscription_refresh.call_count == 2

    # Closing hub cancels the task and calls api.async_close_websocket
    await hub.async_close()
    assert mock_tibber_api.async_close_websocket.await_count == 1
    assert hub._ws_task is None


async def test_multi_home_integration_lifecycle(hass: HomeAssistant):
    """Test setup and unload of multiple homes on the same account sharing a hub."""
    entry_home1 = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_h1",
        unique_id="user@test.com_h1",
        data={
            "username": "user@test.com",
            "password": "secret_password",
            "home_id": "h1",
            "api_key": "shared_public_key",
            "flex_devices": [{"id": "v1", "type": "vehicle"}],
        },
    )
    entry_home2 = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_h2",
        unique_id="user@test.com_h2",
        data={
            "username": "user@test.com",
            "password": "secret_password",
            "home_id": "h2",
            "api_key": "shared_public_key",
            "flex_devices": [{"id": "v2", "type": "vehicle"}],
        },
    )
    entry_home1.add_to_hass(hass)
    entry_home2.add_to_hass(hass)

    with (
        patch(
            "custom_components.tibber_grid_reward.TibberAPI.get_homes",
            AsyncMock(return_value=[{"id": "h1"}, {"id": "h2"}]),
        ) as mock_get_homes,
        patch(
            "custom_components.tibber_grid_reward.DailyRewardTracker.async_setup",
            AsyncMock(),
        ),
        patch(
            "custom_components.tibber_grid_reward.RewardSessionTracker.async_load",
            AsyncMock(),
        ),
        patch(
            "custom_components.tibber_grid_reward.TibberAPI.run_multiplexed_subscription",
            AsyncMock(),
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            AsyncMock(),
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
            AsyncMock(return_value=True),
        ),
    ):
        # Setup home 1
        assert await async_setup_entry(hass, entry_home1) is True
        # Verify credentials checked on first entry
        assert mock_get_homes.call_count == 1

        # Setup home 2
        assert await async_setup_entry(hass, entry_home2) is True
        # Verify credentials NOT checked again (reused hub)
        assert mock_get_homes.call_count == 1

        accounts = hass.data.get(f"{DOMAIN}_accounts", {})
        assert "user@test.com" in accounts
        hub = accounts["user@test.com"]
        assert len(hub.entries) == 2

        # Both entries share the exact same TibberAPI and TibberPublicAPI instances
        api_h1 = hass.data[DOMAIN]["entry_h1"]["api"]
        api_h2 = hass.data[DOMAIN]["entry_h2"]["api"]
        assert api_h1 is api_h2

        pub_h1 = hass.data[DOMAIN]["entry_h1"]["public_api"]
        pub_h2 = hass.data[DOMAIN]["entry_h2"]["public_api"]
        assert pub_h1 is pub_h2

        # Unload home 1
        assert await async_unload_entry(hass, entry_home1) is True
        assert len(hub.entries) == 1
        assert "user@test.com" in hass.data.get(f"{DOMAIN}_accounts", {})

        # Unload home 2
        assert await async_unload_entry(hass, entry_home2) is True
        # Hub has no remaining entries and was closed and removed
        assert "user@test.com" not in hass.data.get(f"{DOMAIN}_accounts", {})


async def test_api_key_sync_on_entry_update(hass: HomeAssistant):
    """Test that a new or rotated API key updates the hub's public_api client."""
    entry_home1 = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_h1",
        unique_id="user@test.com_h1",
        data={
            "username": "user@test.com",
            "password": "secret_password",
            "home_id": "h1",
            "api_key": "initial_key",
            "flex_devices": [],
        },
    )
    entry_home2 = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_h2",
        unique_id="user@test.com_h2",
        data={
            "username": "user@test.com",
            "password": "secret_password",
            "home_id": "h2",
            "api_key": "rotated_key",
            "flex_devices": [],
        },
    )
    entry_home1.add_to_hass(hass)
    entry_home2.add_to_hass(hass)

    with (
        patch(
            "custom_components.tibber_grid_reward.TibberAPI.get_homes",
            AsyncMock(return_value=[{"id": "h1"}, {"id": "h2"}]),
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
            "custom_components.tibber_grid_reward.TibberAPI.run_multiplexed_subscription",
            AsyncMock(),
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            AsyncMock(),
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
            AsyncMock(return_value=True),
        ),
    ):
        assert await async_setup_entry(hass, entry_home1) is True
        hub = hass.data[f"{DOMAIN}_accounts"]["user@test.com"]
        assert hub.public_api._token == "initial_key"

        assert await async_setup_entry(hass, entry_home2) is True
        # Verify hub.public_api was updated with rotated_key
        assert hub.public_api._token == "rotated_key"

        await async_unload_entry(hass, entry_home1)
        await async_unload_entry(hass, entry_home2)
