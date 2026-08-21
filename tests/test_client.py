"""Tests for the Tibber API client."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from custom_components.tibber_grid_reward.client import (
    TibberAPI,
    TibberAuthError,
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
                "value": "true",
            }
        ],
    }
