import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from websockets.asyncio.client import ClientConnection

from custom_components.tibber_grid_reward.client import (
    TibberAPI,
    TibberAuthError,
    TibberException,
)


@pytest.fixture
def client() -> TibberAPI:
    """Return a TibberAPI client."""
    mock_client_instance = MagicMock(spec=httpx.AsyncClient)
    mock_client_instance.post = AsyncMock()
    api = TibberAPI("test@example.com", "password", mock_client_instance)
    return api


async def test_close_websocket_with_current_connection(client: TibberAPI):
    """Closing a current ClientConnection must not use legacy attributes."""
    websocket = AsyncMock(spec_set=ClientConnection)
    client._websocket = websocket

    await client.async_close_websocket()

    websocket.close.assert_awaited_once_with()
    assert client._ws_reconnect is False
    assert client._sub_refresh_event.is_set()


async def test_close_websocket_without_connection_is_repeatable(client: TibberAPI):
    """Repeated shutdown without a connection leaves reconnection disabled."""
    await client.async_close_websocket()
    await client.async_close_websocket()

    assert client._ws_reconnect is False
    assert client._sub_refresh_event.is_set()


async def test_fetch_token(client: TibberAPI):
    """Test fetching a token."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "test_token"}
    client._client.post.return_value = mock_response

    with patch("jwt.decode", return_value={"exp": 9999999999}):
        token = await client.fetch_token()

    assert token == "test_token"


async def test_fetch_token_auth_error(client: TibberAPI):
    """Test fetching a token with an authentication error."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 401
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401 Unauthorized", request=MagicMock(), response=mock_response
    )
    client._client.post.return_value = mock_response

    with pytest.raises(TibberAuthError):
        await client.fetch_token()


async def test_set_smart_charging_enabled(client: TibberAPI):
    """Test setting smart charging enabled."""
    mock_token_response = MagicMock(spec=httpx.Response)
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {"token": "test_token"}

    mock_mutation_response = MagicMock(spec=httpx.Response)
    mock_mutation_response.status_code = 200
    mock_mutation_response.json.return_value = {
        "data": {"me": {"setVehicleSettings": [{"__typename": "Setting"}]}}
    }

    client._client.post.side_effect = [mock_token_response, mock_mutation_response]

    with patch("jwt.decode", return_value={"exp": 9999999999}):
        await client.set_smart_charging_enabled("home1", "vehicle1", True)

    assert client._client.post.call_count == 2
    mutation_call_args = client._client.post.call_args_list[1]
    assert mutation_call_args.kwargs["json"]["variables"] == {
        "vehicleId": "vehicle1",
        "homeId": "home1",
        "settings": [
            {
                "key": "online.vehicle.smartCharging.isEnabled",
                "value": True,
            }
        ],
    }


async def test_set_smart_charging_enabled_offline_fallback(client: TibberAPI):
    """Test setting smart charging enabled with fallback to offline key."""
    mock_token_response = MagicMock(spec=httpx.Response)
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {"token": "test_token"}

    mock_mutation_error = MagicMock(spec=httpx.Response)
    mock_mutation_error.status_code = 200
    mock_mutation_error.json.return_value = {
        "errors": [{"message": "Resource Not Found"}]
    }

    mock_mutation_success = MagicMock(spec=httpx.Response)
    mock_mutation_success.status_code = 200
    mock_mutation_success.json.return_value = {
        "data": {"me": {"setVehicleSettings": [{"__typename": "Setting"}]}}
    }

    client._client.post.side_effect = [
        mock_token_response,
        mock_mutation_error,
        mock_mutation_success,
    ]

    with patch("jwt.decode", return_value={"exp": 9999999999}):
        await client.set_smart_charging_enabled("home1", "vehicle1", True)

    assert client._client.post.call_count == 3
    mutation_offline_call = client._client.post.call_args_list[2]
    assert mutation_offline_call.kwargs["json"]["variables"] == {
        "vehicleId": "vehicle1",
        "homeId": "home1",
        "settings": [
            {
                "key": "offline.vehicle.smartCharging.isEnabled",
                "value": True,
            }
        ],
    }


async def test_set_departure_time(client: TibberAPI):
    """Test setting departure time."""
    mock_token_response = MagicMock(spec=httpx.Response)
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {"token": "test_token"}

    mock_mutation_response = MagicMock(spec=httpx.Response)
    mock_mutation_response.status_code = 200
    mock_mutation_response.json.return_value = {
        "data": {"me": {"setVehicleSettings": [{"__typename": "Setting"}]}}
    }

    client._client.post.side_effect = [mock_token_response, mock_mutation_response]

    with patch("jwt.decode", return_value={"exp": 9999999999}):
        await client.set_departure_time("home1", "vehicle1", "monday", "07:00")

    assert client._client.post.call_count == 2
    mutation_call_args = client._client.post.call_args_list[1]
    assert mutation_call_args.kwargs["json"]["variables"] == {
        "vehicleId": "vehicle1",
        "homeId": "home1",
        "settings": [
            {
                "key": "online.vehicle.smartCharging.departureTimes.monday",
                "value": "07:00",
            }
        ],
    }


async def test_set_departure_time_offline_fallback(client: TibberAPI):
    """Test setting departure time with fallback to offline key."""
    mock_token_response = MagicMock(spec=httpx.Response)
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {"token": "test_token"}

    mock_mutation_error = MagicMock(spec=httpx.Response)
    mock_mutation_error.status_code = 200
    mock_mutation_error.json.return_value = {
        "errors": [{"message": "Resource Not Found"}]
    }

    mock_mutation_success = MagicMock(spec=httpx.Response)
    mock_mutation_success.status_code = 200
    mock_mutation_success.json.return_value = {
        "data": {"me": {"setVehicleSettings": [{"__typename": "Setting"}]}}
    }

    client._client.post.side_effect = [
        mock_token_response,
        mock_mutation_error,
        mock_mutation_success,
    ]

    with patch("jwt.decode", return_value={"exp": 9999999999}):
        await client.set_departure_time("home1", "vehicle1", "monday", "07:00")

    assert client._client.post.call_count == 3
    mutation_offline_call = client._client.post.call_args_list[2]
    assert mutation_offline_call.kwargs["json"]["variables"] == {
        "vehicleId": "vehicle1",
        "homeId": "home1",
        "settings": [
            {
                "key": "offline.vehicle.departureTimes.monday",
                "value": "07:00",
            }
        ],
    }


async def test_get_battery_details(client: TibberAPI):
    """Test fetching consolidated battery details."""
    mock_token_response = MagicMock(spec=httpx.Response)
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {"token": "test_token"}

    mock_query_response = MagicMock(spec=httpx.Response)
    mock_query_response.status_code = 200
    mock_query_response.json.return_value = {
        "data": {
            "me": {
                "home": {
                    "battery": {
                        "aggregatedHistory": {
                            "periods": [
                                {
                                    "key": "TODAY",
                                    "batteryValueItems": [
                                        {"value": 12.34, "unit": "SEK", "kind": "TOTAL"}
                                    ],
                                }
                            ]
                        }
                    },
                    "batteryActivityHistory": {
                        "items": [
                            {
                                "from": "2026-09-19T12:00:00Z",
                                "to": None,
                                "reason": {
                                    "__typename": "HomeBatteryChargingForGridRewards"
                                },
                                "secondaryReason": None,
                            }
                        ]
                    },
                    "batteryTimeline": {
                        "energyFlow": {
                            "items": [
                                {
                                    "kind": "FORECAST",
                                    "time": "2026-09-19T13:00:00Z",
                                    "charged": 2500,
                                    "discharged": 0,
                                }
                            ]
                        },
                        "stateOfCharge": {
                            "items": [
                                {
                                    "kind": "FORECAST",
                                    "time": "2026-09-19T13:00:00Z",
                                    "stateOfCharge": 85.24,
                                }
                            ]
                        },
                    },
                }
            }
        }
    }

    client._client.post.side_effect = [mock_token_response, mock_query_response]

    with patch("jwt.decode", return_value={"exp": 9999999999}):
        details = await client.get_battery_details("home1", "battery1")

    assert "TODAY" in details["savings"]
    assert details["savings"]["TODAY"]["value"] == 12.34
    assert len(details["activity"]) == 1
    assert (
        details["activity"][0]["reason"]["__typename"]
        == "HomeBatteryChargingForGridRewards"
    )
    assert len(details["planned"]) == 1
    assert details["planned"][0]["charged"] == 2500
    assert details["planned"][0]["state_of_charge"] == 85.24


async def test_get_battery_savings_compatibility(client: TibberAPI):
    """Test get_battery_savings backward compatibility wrapper."""
    mock_token_response = MagicMock(spec=httpx.Response)
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {"token": "test_token"}

    mock_query_response = MagicMock(spec=httpx.Response)
    mock_query_response.status_code = 200
    mock_query_response.json.return_value = {
        "data": {
            "me": {
                "home": {
                    "battery": {
                        "aggregatedHistory": {
                            "periods": [
                                {
                                    "key": "MONTH",
                                    "batteryValueItems": [
                                        {"value": 450.0, "unit": "SEK", "kind": "TOTAL"}
                                    ],
                                }
                            ]
                        }
                    }
                }
            }
        }
    }

    client._client.post.side_effect = [mock_token_response, mock_query_response]

    with patch("jwt.decode", return_value={"exp": 9999999999}):
        savings = await client.get_battery_savings("home1", "battery1")

    assert "MONTH" in savings
    assert savings["MONTH"]["value"] == 450.0


async def test_execute_query_blocks(client: TibberAPI):
    """Test execute_query_blocks directly with a mock GraphQLQueryComposer."""
    mock_token_response = MagicMock(spec=httpx.Response)
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {"token": "test_token"}

    mock_query_response = MagicMock(spec=httpx.Response)
    mock_query_response.status_code = 200
    mock_query_response.json.return_value = {"data": {"result": 123}}

    client._client.post.side_effect = [mock_token_response, mock_query_response]

    composer = MagicMock()
    composer.operation_name = "CustomOp"
    composer.build_query.return_value = "query CustomOp { me { id } }"
    composer.build_variables.return_value = {"homeId": "home1"}
    composer.parse_response.return_value = {"custom": 123}

    with patch("jwt.decode", return_value={"exp": 9999999999}):
        res = await client.execute_query_blocks(composer, "home1", device_id="bat1")

    assert res == {"custom": 123}
    composer.build_query.assert_called_once()
    composer.build_variables.assert_called_once()
    composer.parse_response.assert_called_once_with({"result": 123})


async def test_execute_query_blocks_with_block_sequence(client: TibberAPI):
    """Test execute_query_blocks accepting a sequence of blocks without manual composer."""
    from custom_components.tibber_grid_reward.query_blocks import create_query_block

    mock_token_response = MagicMock(spec=httpx.Response)
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {"token": "test_token"}

    mock_query_response = MagicMock(spec=httpx.Response)
    mock_query_response.status_code = 200
    mock_query_response.json.return_value = {
        "data": {
            "me": {
                "home": {
                    "sensor_one": {"val": 10},
                    "sensor_two": {"val": 20},
                }
            }
        }
    }

    client._client.post.side_effect = [mock_token_response, mock_query_response]

    b1 = create_query_block(
        "b1", "sensor_one { val }", lambda d: d.get("sensor_one", {}).get("val")
    )
    b2 = create_query_block(
        "b2", "sensor_two { val }", lambda d: d.get("sensor_two", {}).get("val")
    )

    with patch("jwt.decode", return_value={"exp": 9999999999}):
        res = await client.execute_query_blocks([b1, b2], "home1")

    assert res == {"b1": 10, "b2": 20}


async def test_execute_block_single(client: TibberAPI):
    """Test execute_block executing a single block and unwrapping its result."""
    from custom_components.tibber_grid_reward.query_blocks import create_query_block

    mock_token_response = MagicMock(spec=httpx.Response)
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {"token": "test_token"}

    mock_query_response = MagicMock(spec=httpx.Response)
    mock_query_response.status_code = 200
    mock_query_response.json.return_value = {
        "data": {
            "me": {
                "home": {
                    "solar": {"power": 5500},
                }
            }
        }
    }

    client._client.post.side_effect = [mock_token_response, mock_query_response]

    solar_block = create_query_block(
        "solar",
        "solar { power }",
        lambda d: d.get("solar", {}).get("power"),
    )

    with patch("jwt.decode", return_value={"exp": 9999999999}):
        power = await client.execute_block(solar_block, "home1")

    assert power == 5500


async def test_execute_query_blocks_graphql_error(client: TibberAPI):
    """Test execute_query_blocks raises TibberException on GraphQL errors without data."""
    mock_token_response = MagicMock(spec=httpx.Response)
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {"token": "test_token"}

    mock_error_response = MagicMock(spec=httpx.Response)
    mock_error_response.status_code = 200
    mock_error_response.json.return_value = {
        "errors": [{"message": "Field 'battery' doesn't exist on type 'Home'"}]
    }

    client._client.post.side_effect = [mock_token_response, mock_error_response]

    with (
        patch("jwt.decode", return_value={"exp": 9999999999}),
        pytest.raises(TibberException, match="GraphQL error executing query blocks"),
    ):
        await client.execute_query_blocks(["savings"], "home1")


def test_callback_registration_and_unregistration(client: TibberAPI):
    """Test registering and unregistering callbacks for homes and vehicles."""
    cb1 = MagicMock()
    cb2 = MagicMock()
    vcb1 = MagicMock()
    vcb2 = MagicMock()

    client.register_grid_reward_callback(cb1, home_id="home_1")
    client.register_grid_reward_callback(cb2, home_id="home_2")
    assert client._home_callbacks["home_1"] == [cb1]
    assert client._home_callbacks["home_2"] == [cb2]

    client.register_vehicle_callback("veh_1", vcb1)
    client.register_vehicle_callback("veh_1", vcb2)
    assert client._vehicle_callbacks["veh_1"] == [vcb1, vcb2]

    # Unregister vehicle callback
    client.unregister_vehicle_callback("veh_1", vcb1)
    assert client._vehicle_callbacks["veh_1"] == [vcb2]
    client.unregister_vehicle_callback("veh_1", vcb2)
    assert "veh_1" not in client._vehicle_callbacks

    # Unregister home callback
    client.unregister_grid_reward_callback(cb1, home_id="home_1")
    assert "home_1" not in client._home_callbacks
    client.unregister_grid_reward_callback(cb2)
    assert "home_2" not in client._home_callbacks


def test_dispatch_grid_reward_and_vehicle_state(client: TibberAPI):
    """Test dispatching data routes to appropriate home and vehicle callbacks."""
    cb_home1 = MagicMock()
    cb_home2 = MagicMock()
    cb_faulty = MagicMock(side_effect=RuntimeError("Boom"))
    vcb1 = MagicMock()
    vcb2 = MagicMock()

    client.register_grid_reward_callback(cb_home1, home_id="home_1")
    client.register_grid_reward_callback(cb_faulty, home_id="home_1")
    client.register_grid_reward_callback(cb_home2, home_id="home_2")

    client.register_vehicle_callback("veh_1", vcb1)
    client.register_vehicle_callback("veh_2", vcb2)

    # Dispatch to home 1
    reward_data_h1 = {
        "homeId": "home_1",
        "state": {"__typename": "GridRewardAvailable"},
    }
    client._dispatch_grid_reward(reward_data_h1)

    cb_home1.assert_called_once_with(reward_data_h1)
    cb_faulty.assert_called_once_with(reward_data_h1)
    cb_home2.assert_not_called()

    # Dispatch to vehicle 2
    veh_data_v2 = {"id": "veh_2", "battery": {"level": 75}}
    client._dispatch_vehicle_state("veh_2", veh_data_v2)

    vcb2.assert_called_once_with(veh_data_v2)
    vcb1.assert_not_called()


async def test_multiplexed_subscription_protocol(client: TibberAPI):
    """Test full multiplexed websocket protocol lifecycle, message routing, and ping/pong."""
    mock_token_response = MagicMock(spec=httpx.Response)
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {"token": "test_token"}
    client._client.post.return_value = mock_token_response

    mock_ws = AsyncMock(spec_set=ClientConnection)
    sent_messages: list[dict] = []
    message_event = asyncio.Event()

    async def fake_send(msg_str):
        sent_messages.append(json.loads(msg_str))
        message_event.set()

    mock_ws.send = AsyncMock(side_effect=fake_send)

    async def wait_for_messages(count: int, timeout: float = 3.0):
        while len(sent_messages) < count:
            message_event.clear()
            await asyncio.wait_for(message_event.wait(), timeout=timeout)

    msg_queue: asyncio.Queue[str] = asyncio.Queue()
    mock_ws.recv.side_effect = msg_queue.get

    home_cb_event = asyncio.Event()
    veh_cb_event = asyncio.Event()

    def on_home_cb(data):
        home_cb_event.set()

    def on_veh_cb(data):
        veh_cb_event.set()

    home_cb = MagicMock(side_effect=on_home_cb)
    veh_cb = MagicMock(side_effect=on_veh_cb)
    client.register_grid_reward_callback(home_cb, home_id="h1")
    client.register_vehicle_callback("v1", veh_cb)

    active_homes = {"h1"}
    active_vehicles = {"v1"}

    def get_targets():
        return active_homes, active_vehicles

    sub_task = None
    with (
        patch("jwt.decode", return_value={"exp": 9999999999}),
        patch(
            "custom_components.tibber_grid_reward.client.websockets.connect"
        ) as mock_connect,
    ):
        mock_connect.return_value.__aenter__.return_value = mock_ws

        sub_task = asyncio.create_task(client.run_multiplexed_subscription(get_targets))

        # Wait for connection_init to be sent
        await wait_for_messages(1)
        assert sent_messages[0]["type"] == "connection_init"

        # 1. Acknowledge connection
        await msg_queue.put(json.dumps({"type": "connection_ack"}))
        # Wait for subscriptions for h1 and v1
        await wait_for_messages(3)

        sub_types = {m["payload"]["operationName"] for m in sent_messages[1:3]}
        assert sub_types == {"gridRewardsSubscription", "vehicleStateSubscription"}

        home_sub_id = next(
            m["id"]
            for m in sent_messages
            if m.get("payload", {}).get("operationName") == "gridRewardsSubscription"
        )
        veh_sub_id = next(
            m["id"]
            for m in sent_messages
            if m.get("payload", {}).get("operationName") == "vehicleStateSubscription"
        )

        # 2. Server sends ping
        await msg_queue.put(json.dumps({"type": "ping"}))
        await wait_for_messages(4)
        assert sent_messages[-1] == {"type": "pong"}

        # 3. Next message for grid reward
        await msg_queue.put(
            json.dumps(
                {
                    "type": "next",
                    "id": home_sub_id,
                    "payload": {
                        "data": {
                            "gridRewardStatus": {
                                "homeId": "h1",
                                "state": {"__typename": "GridRewardAvailable"},
                            }
                        }
                    },
                }
            )
        )
        await asyncio.wait_for(home_cb_event.wait(), timeout=3.0)
        assert home_cb.call_count == 1
        assert home_cb.call_args[0][0]["homeId"] == "h1"

        # 4. Next message for vehicle
        await msg_queue.put(
            json.dumps(
                {
                    "type": "next",
                    "id": veh_sub_id,
                    "payload": {
                        "data": {
                            "vehicleState": {
                                "id": "v1",
                                "battery": {"level": 88},
                            }
                        }
                    },
                }
            )
        )
        await asyncio.wait_for(veh_cb_event.wait(), timeout=3.0)
        assert veh_cb.call_count == 1
        assert veh_cb.call_args[0][0]["id"] == "v1"

        # 5. Dynamic subscription refresh (add h2, remove v1)
        active_homes.add("h2")
        active_vehicles.remove("v1")
        client.trigger_subscription_refresh()
        await wait_for_messages(6)

        # Check new subscribe for h2 and complete for v1 sent
        assert any(
            m.get("payload", {}).get("variables", {}).get("homeId") == "h2"
            for m in sent_messages
        )
        assert any(
            m.get("type") == "complete" and m.get("id") == veh_sub_id
            for m in sent_messages
        )

        # 6. Close websocket
        await client.close_websocket()
        await asyncio.wait_for(sub_task, timeout=3.0)
        assert sub_task.done()


def test_callback_registration_deduplication(client: TibberAPI):
    """Test registering the exact same callback repeatedly does not produce duplicate entries."""
    cb = MagicMock()
    vcb = MagicMock()

    client.register_grid_reward_callback(cb, home_id="home_1")
    client.register_grid_reward_callback(cb, home_id="home_1")
    assert client._home_callbacks["home_1"] == [cb]

    client.register_vehicle_callback("veh_1", vcb)
    client.register_vehicle_callback("veh_1", vcb)
    assert client._vehicle_callbacks["veh_1"] == [vcb]


async def test_multiplexed_subscription_server_error_cleans_mapping(client: TibberAPI):
    """Test server error removes subscription from sub_map and target_map."""
    mock_token_response = MagicMock(spec=httpx.Response)
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {"token": "test_token"}
    client._client.post.return_value = mock_token_response

    mock_ws = AsyncMock(spec_set=ClientConnection)
    sent_messages: list[dict] = []
    message_event = asyncio.Event()

    async def fake_send(msg_str):
        sent_messages.append(json.loads(msg_str))
        message_event.set()

    mock_ws.send = AsyncMock(side_effect=fake_send)

    async def wait_for_messages(count: int, timeout: float = 3.0):
        while len(sent_messages) < count:
            message_event.clear()
            await asyncio.wait_for(message_event.wait(), timeout=timeout)

    msg_queue: asyncio.Queue[str] = asyncio.Queue()
    mock_ws.recv.side_effect = msg_queue.get

    active_homes = {"h1"}
    active_vehicles = set()

    sub_task = None
    with (
        patch("jwt.decode", return_value={"exp": 9999999999}),
        patch(
            "custom_components.tibber_grid_reward.client.websockets.connect"
        ) as mock_connect,
    ):
        mock_connect.return_value.__aenter__.return_value = mock_ws
        sub_task = asyncio.create_task(
            client.run_multiplexed_subscription(lambda: (active_homes, active_vehicles))
        )

        await wait_for_messages(1)
        await msg_queue.put(json.dumps({"type": "connection_ack"}))
        await wait_for_messages(2)

        sub_id = sent_messages[1]["id"]

        # Server sends error for the subscription
        await msg_queue.put(
            json.dumps(
                {
                    "type": "error",
                    "id": sub_id,
                    "payload": [{"message": "Subscription rate limit"}],
                }
            )
        )

        # Allow the event loop to process the incoming error message from msg_queue
        await asyncio.sleep(0.05)

        # Trigger refresh and verify target is re-subscribed since mapping was purged
        client.trigger_subscription_refresh()
        await wait_for_messages(3)
        assert sent_messages[-1]["type"] == "subscribe"
        assert sent_messages[-1]["id"] != sub_id

        await client.close_websocket()
        await asyncio.wait_for(sub_task, timeout=3.0)
        assert sub_task.done()
