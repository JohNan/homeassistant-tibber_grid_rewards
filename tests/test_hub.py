"""Tests for TibberAccountHub and unified account lifecycle."""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tibber_grid_reward import async_setup_entry, async_unload_entry
from custom_components.tibber_grid_reward.client import TibberAPI
from custom_components.tibber_grid_reward.const import DOMAIN
from custom_components.tibber_grid_reward.coordinator import (
    TibberBatteryDataCoordinator,
)
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


async def test_setup_preserves_unselected_registry_device_and_entities(
    hass: HomeAssistant,
):
    """A normal setup preserves devices until reconfiguration is saved."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_h1",
        data={
            "username": "user@test.com",
            "password": "secret_password",
            "home_id": "h1",
            "flex_devices": [
                {"id": "flex2", "type": "battery", "name": "Current battery"},
                {"id": "flex3", "type": "vehicle", "name": "Kept missing car"},
            ],
        },
    )
    other_entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_h2",
        data={
            "username": "user@test.com",
            "password": "secret_password",
            "home_id": "h2",
            "flex_devices": [{"id": "flex1", "type": "vehicle"}],
        },
    )
    entry.add_to_hass(hass)
    other_entry.add_to_hass(hass)

    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    parent = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.entry_id)}
    )
    unselected = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "flex1")}
    )
    current = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "flex2")}
    )
    kept_missing = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "flex3")}
    )
    same_id_other_home = devices.async_get_or_create(
        config_entry_id=other_entry.entry_id, identifiers={(DOMAIN, "flex1")}
    )
    unselected_entity = entities.async_get_or_create(
        "sensor", DOMAIN, "flex1_state", config_entry=entry, device_id=unselected.id
    )
    current_entity = entities.async_get_or_create(
        "sensor", DOMAIN, "flex2_state", config_entry=entry, device_id=current.id
    )

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
    ):
        assert await async_setup_entry(hass, entry) is True
        await hass.async_block_till_done()

    assert devices.async_get(unselected.id) is not None
    assert entities.async_get(unselected_entity.entity_id) is not None
    assert devices.async_get(parent.id) is not None
    assert devices.async_get(current.id) is not None
    assert devices.async_get(kept_missing.id) is not None
    assert devices.async_get(same_id_other_home.id) is not None
    assert entities.async_get(current_entity.entity_id) is not None


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


async def test_grid_reward_push_refreshes_batteries(hass, mock_tibber_api):
    """A WebSocket update must refresh every battery's telemetry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@test.com_home1",
        data={
            "username": "user@test.com",
            "password": "password",
            "home_id": "home1",
            "flex_devices": [
                {"id": "battery1", "type": "battery"},
                {"id": "battery2", "type": "battery"},
            ],
        },
    )
    entry.add_to_hass(hass)
    mock_tibber_api.get_homes = AsyncMock(return_value=[{"id": "home1"}])
    mock_tibber_api.execute_query_blocks = AsyncMock(
        return_value={"savings": {"TODAY": {"value": 12.5}}}
    )

    with (
        patch(
            "custom_components.tibber_grid_reward.TibberAPI",
            return_value=mock_tibber_api,
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
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            AsyncMock(),
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
            AsyncMock(return_value=True),
        ),
    ):
        assert await async_setup_entry(hass, entry)
        entry_data = hass.data[DOMAIN][entry.entry_id]
        update_callback = entry_data["hub"]._home_callbacks[entry.entry_id]
        coordinators = entry_data["battery_coordinators"]
        for battery_id in ("battery1", "battery2"):
            coordinators[battery_id] = TibberBatteryDataCoordinator(
                hass, mock_tibber_api, "home1", battery_id, config_entry=entry
            )

        try:
            update_callback({})
            await hass.async_block_till_done()

            for coordinator in coordinators.values():
                assert coordinator.data is not None
                assert coordinator.data.savings["TODAY"]["value"] == 12.5

            assert await async_unload_entry(hass, entry)
            mock_tibber_api.execute_query_blocks.reset_mock()
            update_callback({})
            await hass.async_block_till_done()
            mock_tibber_api.execute_query_blocks.assert_not_awaited()
        finally:
            for coordinator in coordinators.values():
                await coordinator.async_shutdown()


async def test_unload_cancels_inflight_battery_refresh(hass):
    """A blocked battery request must not survive unloading its config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@test.com_h1",
        data={
            "username": "user@test.com",
            "password": "password",
            "home_id": "h1",
            "flex_devices": [{"id": "bat1", "type": "battery", "name": "Battery"}],
        },
    )
    entry.add_to_hass(hass)
    started, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def blocked_refresh():
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with (
        patch("custom_components.tibber_grid_reward.PLATFORMS", ["binary_sensor"]),
        patch(
            "custom_components.tibber_grid_reward.TibberAPI.get_homes",
            AsyncMock(return_value=[{"id": "h1"}]),
        ),
        patch(
            "custom_components.tibber_grid_reward.TibberAPI.run_multiplexed_subscription",
            AsyncMock(),
        ),
        patch(
            "custom_components.tibber_grid_reward.DailyRewardTracker.async_setup",
            AsyncMock(),
        ),
        patch(
            "custom_components.tibber_grid_reward.RewardSessionTracker.async_load",
            AsyncMock(),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        entry_data = hass.data[DOMAIN][entry.entry_id]
        coordinator = MagicMock()
        coordinator.async_request_refresh = blocked_refresh
        entry_data["battery_coordinators"]["bat1"] = coordinator
        entry_data["hub"]._home_callbacks[entry.entry_id]({})
        await asyncio.wait_for(started.wait(), 1)
        try:
            assert await asyncio.wait_for(
                hass.config_entries.async_unload(entry.entry_id), 1
            )
            assert cancelled.is_set()
        finally:
            release.set()
            await hass.async_block_till_done()


async def test_device_links_exist_before_platform_setup(hass, mock_tibber_api):
    """Platforms may register flex entities before home-level entities."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_h1",
        unique_id="user@test.com_h1",
        data={
            "username": "user@test.com",
            "password": "password",
            "home_id": "h1",
            "flex_devices": [
                {"id": "car1", "type": "vehicle", "name": "Car"},
                {"id": "bat1", "type": "battery", "name": "Battery"},
            ],
        },
    )
    entry.add_to_hass(hass)
    mock_tibber_api.get_homes = AsyncMock(return_value=[{"id": "h1"}])
    seen = []

    async def inspect_before_platforms(config_entry, platforms):
        registry = dr.async_get(hass)
        devices = dr.async_entries_for_config_entry(registry, config_entry.entry_id)
        by_identifier = {
            identifier: device
            for device in devices
            for identifier in device.identifiers
        }
        parent = by_identifier[(DOMAIN, config_entry.entry_id)]
        for identifier in ("car1", "bat1"):
            child = by_identifier[(DOMAIN, identifier)]
            assert child.via_device_id == parent.id
            seen.append(identifier)

    with (
        patch(
            "custom_components.tibber_grid_reward.TibberAPI",
            return_value=mock_tibber_api,
        ),
        patch(
            "custom_components.tibber_grid_reward.DailyRewardTracker.async_setup",
            AsyncMock(),
        ),
        patch(
            "custom_components.tibber_grid_reward.RewardSessionTracker.async_load",
            AsyncMock(),
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            side_effect=inspect_before_platforms,
        ),
    ):
        assert await async_setup_entry(hass, entry)
        assert seen == ["car1", "bat1"]


async def test_shared_flex_device_keeps_existing_parent(hass):
    """A second home must not reparent or create an empty duplicate device."""

    def make_entry(home):
        return MockConfigEntry(
            domain=DOMAIN,
            entry_id=f"entry_{home}",
            unique_id=f"user@test.com_{home}",
            data={
                "username": "user@test.com",
                "password": "password",
                "home_id": home,
                "flex_devices": [
                    {"id": "shared_car", "type": "vehicle", "name": "Car"}
                ],
            },
        )

    first, second = make_entry("h1"), make_entry("h2")
    first.add_to_hass(hass)
    with (
        patch("custom_components.tibber_grid_reward.PLATFORMS", ["binary_sensor"]),
        patch(
            "custom_components.tibber_grid_reward.TibberAPI.get_homes",
            AsyncMock(return_value=[{"id": "h1"}, {"id": "h2"}]),
        ),
        patch(
            "custom_components.tibber_grid_reward.TibberAPI.run_multiplexed_subscription",
            AsyncMock(),
        ),
        patch(
            "custom_components.tibber_grid_reward.DailyRewardTracker.async_setup",
            AsyncMock(),
        ),
        patch(
            "custom_components.tibber_grid_reward.RewardSessionTracker.async_load",
            AsyncMock(),
        ),
    ):
        assert await hass.config_entries.async_setup(first.entry_id)
        await hass.async_block_till_done()
        registry = dr.async_get(hass)
        entities = er.async_get(hass)
        entity_id = entities.async_get_entity_id(
            "binary_sensor", DOMAIN, "shared_car_grid_reward_active"
        )
        original_id = entities.async_get(entity_id).device_id
        original_parent = registry.async_get(original_id).via_device_id
        assert original_parent is not None

        second.add_to_hass(hass)
        assert await hass.config_entries.async_setup(second.entry_id)
        await hass.async_block_till_done()

        assert registry.async_get(original_id).via_device_id == original_parent
        other_flex_devices = [
            device
            for device in dr.async_entries_for_config_entry(registry, second.entry_id)
            if (DOMAIN, "shared_car") in device.identifiers
        ]
        assert all(device.id == original_id for device in other_flex_devices)

        assert await hass.config_entries.async_unload(second.entry_id)
        assert await hass.config_entries.async_unload(first.entry_id)

        # Once the original owner is unloaded, the other home may claim it.
        assert await hass.config_entries.async_setup(second.entry_id)
        await hass.async_block_till_done()
        moved_entity = entities.async_get(entity_id)
        assert moved_entity.config_entry_id == second.entry_id
        moved_device = registry.async_get(moved_entity.device_id)
        moved_parent = registry.async_get(moved_device.via_device_id)
        assert (DOMAIN, second.entry_id) in moved_parent.identifiers
        assert await hass.config_entries.async_unload(second.entry_id)


@pytest.mark.parametrize("preexisting", [False, True])
async def test_device_links_survive_setup_and_reload(hass, preexisting, caplog):
    """Real entities keep their home and flex device identities and links."""
    entries = []
    for home, devices in (
        ("h1", [{"id": "v1", "type": "vehicle", "name": "Car"}]),
        ("h2", [{"id": "b2", "type": "battery", "name": "Battery"}]),
    ):
        entry = MockConfigEntry(
            domain=DOMAIN,
            entry_id=f"entry_{home}",
            unique_id=f"user@test.com_{home}",
            data={
                "username": "user@test.com",
                "password": "password",
                "home_id": home,
                "flex_devices": devices,
            },
        )
        entry.add_to_hass(hass)
        entries.append(entry)

    registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    previous = {}
    if preexisting:
        for entry in entries:
            parent = registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, entry.entry_id)},
                name="Tibber Grid Reward",
                manufacturer="Tibber",
            )
            flex = entry.data["flex_devices"][0]
            child = registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, flex["id"])},
                name=flex["name"],
                manufacturer="Tibber",
            )
            registry.async_update_device(child.id, via_device_id=parent.id)
            previous[entry.entry_id] = (parent.id, child.id)

    with (
        patch(
            "custom_components.tibber_grid_reward.TibberAPI.get_homes",
            AsyncMock(return_value=[{"id": "h1"}, {"id": "h2"}]),
        ),
        patch(
            "custom_components.tibber_grid_reward.TibberAPI.execute_query_blocks",
            AsyncMock(return_value={}),
        ),
        patch(
            "custom_components.tibber_grid_reward.TibberAPI.run_multiplexed_subscription",
            AsyncMock(),
        ),
        patch(
            "custom_components.tibber_grid_reward.DailyRewardTracker.async_setup",
            AsyncMock(),
        ),
        patch(
            "custom_components.tibber_grid_reward.RewardSessionTracker.async_load",
            AsyncMock(),
        ),
    ):
        # Setting up the domain also starts the other existing config entry.
        assert await hass.config_entries.async_setup(entries[0].entry_id)
        await hass.async_block_till_done()
        assert all(entry.entry_id in hass.data[DOMAIN] for entry in entries)

        def get_device_ids(entry):
            flex_id = entry.data["flex_devices"][0]["id"]
            parent_entity_id = entity_registry.async_get_entity_id(
                "binary_sensor", DOMAIN, f"{entry.entry_id}_grid_reward_active"
            )
            flex_entity_id = entity_registry.async_get_entity_id(
                "binary_sensor", DOMAIN, f"{flex_id}_grid_reward_active"
            )
            parent_entity = entity_registry.async_get(parent_entity_id)
            flex_entity = entity_registry.async_get(flex_entity_id)
            parent = registry.async_get(parent_entity.device_id)
            child = registry.async_get(flex_entity.device_id)
            assert parent.identifiers == {(DOMAIN, entry.entry_id)}
            assert child.identifiers == {(DOMAIN, flex_id)}
            assert child.via_device_id == parent.id
            return parent.id, child.id

        first_ids = {entry.entry_id: get_device_ids(entry) for entry in entries}
        if preexisting:
            assert first_ids == previous
        assert first_ids["entry_h1"][0] != first_ids["entry_h2"][0]
        assert "deprecated `via_device` parameter" not in caplog.text

        for entry in entries:
            assert await hass.config_entries.async_unload(entry.entry_id)
            assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert {entry.entry_id: get_device_ids(entry) for entry in entries} == first_ids
        for entry in entries:
            assert len(dr.async_entries_for_config_entry(registry, entry.entry_id)) == 2
            assert await hass.config_entries.async_unload(entry.entry_id)
