
from unittest.mock import AsyncMock, MagicMock, patch
import jwt
import httpx
import websockets
import pytest

from custom_components.tibber_grid_reward.client import TibberAPI, TibberAuthError, TibberException, TibberConnectionError

@pytest.fixture
def api():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    return TibberAPI("test_user", "test_pass", mock_client)

@patch("time.time")
async def test_fetch_token_success(mock_time, api):
    mock_time.return_value = 1678886400
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "token": jwt.encode({"exp": 1678886400 + 3600}, "secret", algorithm="HS256")
    }
    api._client.post.return_value = mock_response

    token = await api.fetch_token()
    assert token is not None
    assert token == api._cached_token
    api._client.post.assert_called_once()

@patch("time.time")
async def test_fetch_token_cached(mock_time, api):
    mock_time.return_value = 1678886400
    api._cached_token = "test_token"
    api._cached_exp = 1678886400 + 3600

    token = await api.fetch_token()
    assert token == "test_token"
    api._client.post.assert_not_called()

async def test_fetch_token_auth_error(api):
    api._client.post.side_effect = httpx.HTTPStatusError(
        "Auth error", request=MagicMock(), response=MagicMock()
    )
    with pytest.raises(TibberAuthError):
        await api.fetch_token()

async def test_fetch_token_generic_error(api):
    api._client.post.side_effect = Exception("Generic error")
    with pytest.raises(TibberException):
        await api.fetch_token()

@patch("custom_components.tibber_grid_reward.client.TibberAPI.fetch_token", new_callable=AsyncMock)
async def test_get_homes_success(mock_fetch_token, api):
    mock_fetch_token.return_value = "test_token"
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {"me": {"homes": [{"id": "home1"}, {"id": "home2"}]}}
    }
    api._client.post.return_value = mock_response

    homes = await api.get_homes()
    assert len(homes) == 2
    assert homes[0]["id"] == "home1"
    api._client.post.assert_called_once()

@patch("custom_components.tibber_grid_reward.client.TibberAPI.fetch_token", new_callable=AsyncMock)
async def test_get_homes_connection_error(mock_fetch_token, api):
    mock_fetch_token.return_value = "test_token"
    api._client.post.side_effect = httpx.HTTPStatusError(
        "Connection error", request=MagicMock(), response=MagicMock()
    )
    with pytest.raises(TibberConnectionError):
        await api.get_homes()

@patch("websockets.connect")
@patch("custom_components.tibber_grid_reward.client.TibberAPI.fetch_token", new_callable=AsyncMock)
async def test_validate_grid_reward_success(mock_fetch_token, mock_ws_connect, api):
    mock_fetch_token.return_value = "test_token"
    mock_websocket = AsyncMock()
    mock_ws_connect.return_value.__aenter__.return_value = mock_websocket
    
    async def mock_recv():
        return '{"type": "connection_ack"}'
    
    async def mock_recv2():
        return '{"type": "next", "payload": {"data": {"gridRewardStatus": {"status": "ok"}}}}'

    mock_websocket.recv.side_effect = [await mock_recv(), await mock_recv2()]

    result = await api.validate_grid_reward("home1")
    assert result == {"status": "ok"}
    mock_websocket.send.assert_any_call('{"type": "connection_init"}')

@patch("websockets.connect")
@patch("custom_components.tibber_grid_reward.client.TibberAPI.fetch_token", new_callable=AsyncMock)
async def test_validate_grid_reward_connection_error(mock_fetch_token, mock_ws_connect, api):
    mock_fetch_token.return_value = "test_token"
    mock_ws_connect.side_effect = websockets.exceptions.WebSocketException("Connection failed")

    with pytest.raises(TibberConnectionError):
        await api.validate_grid_reward("home1")

@patch("custom_components.tibber_grid_reward.client.TibberAPI.fetch_token", new_callable=AsyncMock)
async def test_set_departure_time_success(mock_fetch_token, api):
    mock_fetch_token.return_value = "test_token"
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    api._client.post.return_value = mock_response

    await api.set_departure_time("home1", "vehicle1", "monday", "08:00")
    api._client.post.assert_called_once()

@patch("custom_components.tibber_grid_reward.client.TibberAPI.fetch_token", new_callable=AsyncMock)
async def test_set_departure_time_connection_error(mock_fetch_token, api):
    mock_fetch_token.return_value = "test_token"
    api._client.post.side_effect = httpx.HTTPStatusError(
        "Connection error", request=MagicMock(), response=MagicMock()
    )

    with pytest.raises(TibberConnectionError):
        await api.set_departure_time("home1", "vehicle1", "monday", "08:00")
