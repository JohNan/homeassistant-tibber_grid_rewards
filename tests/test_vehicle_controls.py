"""Regression tests for vehicle controls using a shared account API."""

import datetime
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from custom_components.tibber_grid_reward import number, switch, time
from custom_components.tibber_grid_reward.client import TibberAPI, TibberException
from custom_components.tibber_grid_reward.const import DOMAIN


async def setup_controls(hass, api, platform, home_id):
    """Set up a real control platform with Home Assistant state writes mocked."""
    entry = SimpleNamespace(entry_id=home_id, data={"home_id": home_id})
    device = {"id": f"vehicle_{home_id}", "type": "vehicle", "name": "My Car"}
    entry_data = {
        "api": api,
        "flex_devices": [device],
        "grid_reward_devices": [],
        "vehicle_devices": {device["id"]: []},
    }
    hass.data[DOMAIN][home_id] = entry_data
    entities = []
    await platform.async_setup_entry(hass, entry, entities.extend)
    return entities, entry_data["vehicle_devices"][device["id"]]


def resolve_battery_control(entities, vehicle_devices):
    """Deliver the offline state that creates the battery number entity."""
    for control in list(vehicle_devices):
        control.update_data({"isAlive": False, "battery": {"level": 40}})
    return entities[0]


async def change_control(control, action):
    """Exercise the public Home Assistant control method."""
    if action == "battery_level":
        await control.async_set_native_value(60)
    elif action == "departure_time":
        await control.async_set_value(datetime.time(9, 30))
    elif action == "smart_charging_on":
        await control.async_turn_on()
    else:
        await control.async_turn_off()


@pytest.mark.parametrize(
    ("platform", "action"),
    [
        (number, "battery_level"),
        (time, "departure_time"),
        (switch, "smart_charging_on"),
        (switch, "smart_charging_off"),
    ],
)
async def test_shared_api_controls_send_their_configured_home(platform, action):
    """A shared API without a home must still write to each entry's own home."""
    requests = []

    def handle_request(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"data": {"me": {"setVehicleSettings": [{"__typename": "Setting"}]}}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as http:
        api = TibberAPI("test@example.com", "password", http)
        api._cached_token = "test_token"
        api._cached_exp = float("inf")
        hass = MagicMock()
        hass.data = {DOMAIN: {}}
        controls = {}
        pending = {}
        for home_id in ("home_1", "home_2"):
            pending[home_id] = await setup_controls(hass, api, platform, home_id)

        # Resolve battery entities after both homes are registered. Their
        # delayed creation must retain the home belonging to the manager.
        for home_id, (entities, vehicle_devices) in pending.items():
            control = (
                resolve_battery_control(entities, vehicle_devices)
                if platform is number
                else entities[0]
            )
            control.hass = hass
            control.async_write_ha_state = MagicMock()
            controls[home_id] = control

        for home_id in ("home_2", "home_1", "home_2"):
            await change_control(controls[home_id], action)

    assert [request["variables"]["homeId"] for request in requests] == [
        "home_2",
        "home_1",
        "home_2",
    ]
    assert [request["variables"]["vehicleId"] for request in requests] == [
        "vehicle_home_2",
        "vehicle_home_1",
        "vehicle_home_2",
    ]


@pytest.mark.parametrize(
    ("platform", "action", "state_property", "initial_value"),
    [
        (number, "battery_level", "native_value", 40),
        (time, "departure_time", "native_value", datetime.time(8)),
        (switch, "smart_charging_on", "is_on", False),
        (switch, "smart_charging_off", "is_on", True),
    ],
)
async def test_rejected_control_write_preserves_state(
    platform, action, state_property, initial_value
):
    """An HTTP 200 GraphQL rejection must not be displayed as a successful edit."""

    def handle_request(request):
        return httpx.Response(200, json={"errors": [{"message": "Rejected setting"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as http:
        api = TibberAPI("test@example.com", "password", http)
        api._cached_token = "test_token"
        api._cached_exp = float("inf")
        hass = MagicMock()
        hass.data = {DOMAIN: {}}
        entities, vehicle_devices = await setup_controls(hass, api, platform, "home_1")
        control = (
            resolve_battery_control(entities, vehicle_devices)
            if platform is number
            else entities[0]
        )
        control.hass = hass
        control.async_write_ha_state = MagicMock()
        if platform is time:
            control.update_data(
                {
                    "userSettings": [
                        {
                            "key": "offline.vehicle.departureTimes.monday",
                            "value": "08:00",
                        }
                    ]
                }
            )
        elif platform is switch:
            control.update_data(
                {
                    "userSettings": [
                        {
                            "key": "offline.vehicle.smartCharging.isEnabled",
                            "value": initial_value,
                        }
                    ]
                }
            )

        with pytest.raises(TibberException, match="Rejected setting"):
            await change_control(control, action)

        assert getattr(control, state_property) == initial_value
