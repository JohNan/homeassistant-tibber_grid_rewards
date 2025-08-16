
"""Tests for the Tibber API client."""
from unittest.mock import patch

import pytest
from custom_components.tibber_grid_reward.client import TibberAPI, TibberAuthError


@pytest.fixture
def client():
    """Return a TibberAPI client."""
    with patch("httpx.AsyncClient") as mock_client:
        yield TibberAPI("test@example.com", "password", mock_client)


async def test_fetch_token(client: TibberAPI):
    """Test fetching a token."""
    client._client.post.return_value.status_code = 200
    client._client.post.return_value.json.return_value = {"token": "test_token"}
    token = await client.fetch_token()
    assert token == "test_token"


async def test_fetch_token_auth_error(client: TibberAPI):
    """Test fetching a token with an authentication error."""
    client._client.post.return_value.status_code = 401
    with pytest.raises(TibberAuthError):
        await client.fetch_token()
