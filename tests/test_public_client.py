"""Tests for TibberPublicAPI client."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from custom_components.tibber_grid_reward.public_client import (
    TibberPublicAPI,
    TibberPublicAuthError,
    TibberPublicException,
)


@pytest.fixture
def mock_httpx_client():
    """Mock an httpx AsyncClient."""
    client = MagicMock(spec=httpx.AsyncClient)
    client.post = AsyncMock()
    return client


async def test_get_homes_success(mock_httpx_client):
    """Test get_homes parses home addresses and nicknames properly."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {
        "data": {
            "viewer": {
                "homes": [
                    {
                        "id": "home1",
                        "appNickname": "Cabin",
                        "address": {"address1": "Main St 1"},
                    },
                    {
                        "id": "home2",
                        "appNickname": None,
                        "address": {"address1": "Oak Ave 2"},
                    },
                ]
            }
        }
    }
    mock_httpx_client.post.return_value = response

    api = TibberPublicAPI("test_token", mock_httpx_client)
    homes = await api.get_homes()

    assert len(homes) == 2
    assert homes[0]["title"] == "Cabin"
    assert homes[1]["title"] == "Oak Ave 2"


async def test_get_homes_auth_error(mock_httpx_client):
    """Test get_homes raises TibberPublicAuthError on 401."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 401
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401", request=MagicMock(), response=response
    )
    mock_httpx_client.post.return_value = response

    api = TibberPublicAPI("invalid_token", mock_httpx_client)
    with pytest.raises(TibberPublicAuthError):
        await api.get_homes()


async def test_get_homes_generic_error(mock_httpx_client):
    """Test get_homes raises TibberPublicException on network failure."""
    mock_httpx_client.post.side_effect = httpx.ConnectError("Network down")

    api = TibberPublicAPI("test_token", mock_httpx_client)
    with pytest.raises(TibberPublicException):
        await api.get_homes()


async def test_get_all_homes_price_info_batches_and_caches(mock_httpx_client):
    """Test get_all_homes_price_info retrieves and caches prices for multiple homes."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {
        "data": {
            "viewer": {
                "homes": [
                    {
                        "id": "home1",
                        "currentSubscription": {
                            "priceInfo": {
                                "today": [
                                    {"total": 1.5, "startsAt": "2026-09-22T00:00:00Z"}
                                ]
                            }
                        },
                    },
                    {
                        "id": "home2",
                        "currentSubscription": {
                            "priceInfo": {
                                "today": [
                                    {"total": 2.0, "startsAt": "2026-09-22T00:00:00Z"}
                                ]
                            }
                        },
                    },
                ]
            }
        }
    }
    mock_httpx_client.post.return_value = response

    api = TibberPublicAPI("test_token", mock_httpx_client)
    results = await api.get_all_homes_price_info()

    assert mock_httpx_client.post.call_count == 1
    assert "home1" in results
    assert "home2" in results
    assert results["home1"]["today"][0]["total"] == 1.5
    assert results["home2"]["today"][0]["total"] == 2.0

    # Subsequent individual calls to get_price_info should hit the cache without network calls
    price1 = await api.get_price_info("home1")
    price2 = await api.get_price_info("home2")

    assert price1 == results["home1"]
    assert price2 == results["home2"]
    assert mock_httpx_client.post.call_count == 1


async def test_get_price_info_fallback(mock_httpx_client):
    """Test get_price_info falls back to single-home query if not present in batch response."""
    # First response for get_all_homes_price_info (returns empty homes)
    batch_response = MagicMock(spec=httpx.Response)
    batch_response.status_code = 200
    batch_response.json.return_value = {"data": {"viewer": {"homes": []}}}

    # Fallback single home response
    fallback_response = MagicMock(spec=httpx.Response)
    fallback_response.status_code = 200
    fallback_response.json.return_value = {
        "data": {
            "viewer": {
                "home": {
                    "currentSubscription": {"priceInfo": {"today": [{"total": 0.99}]}}
                }
            }
        }
    }
    mock_httpx_client.post.side_effect = [batch_response, fallback_response]

    api = TibberPublicAPI("test_token", mock_httpx_client)
    price = await api.get_price_info("unlisted_home")

    assert mock_httpx_client.post.call_count == 2
    assert price == {"today": [{"total": 0.99}]}
