"""Tests for the Tibber API client."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

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
