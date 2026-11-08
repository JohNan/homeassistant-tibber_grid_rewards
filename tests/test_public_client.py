"""Tests for TibberPublicAPI client."""

from datetime import UTC, datetime, timedelta
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


async def test_get_price_info_negative_caching(mock_httpx_client):
    """Test get_price_info caches None for homes without active subscriptions."""
    batch_response = MagicMock(spec=httpx.Response)
    batch_response.status_code = 200
    batch_response.json.return_value = {
        "data": {
            "viewer": {
                "homes": [
                    {"id": "no_sub_home", "currentSubscription": None},
                ]
            }
        }
    }
    mock_httpx_client.post.return_value = batch_response

    api = TibberPublicAPI("test_token", mock_httpx_client)
    price = await api.get_price_info("no_sub_home")
    assert price is None
    assert mock_httpx_client.post.call_count == 1

    # Subsequent call within 6 hours should hit cache and not make any further network calls
    price_again = await api.get_price_info("no_sub_home")
    assert price_again is None
    assert mock_httpx_client.post.call_count == 1


def _response(payload, status_code=200):
    """Build a real HTTP response without contacting the API."""
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("POST", "https://api.tibber.com/v1-beta/gql"),
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"data": None},
        {"data": {"viewer": None}},
        {"data": {"viewer": {"homes": None}}},
    ],
)
async def test_get_homes_handles_null_response_fields(mock_httpx_client, payload):
    """Nullable GraphQL containers should not cause attribute errors."""
    mock_httpx_client.post.return_value = _response(payload)
    api = TibberPublicAPI("test_token", mock_httpx_client)

    assert await api.get_homes() == []


async def test_get_homes_skips_null_entries(mock_httpx_client):
    """A null home should not hide the remaining valid homes."""
    mock_httpx_client.post.return_value = _response(
        {"data": {"viewer": {"homes": [None, {"id": "home1"}]}}}
    )
    api = TibberPublicAPI("test_token", mock_httpx_client)

    assert await api.get_homes() == [{"id": "home1", "title": "home1"}]


@pytest.mark.parametrize(
    "payload",
    [
        {"data": None},
        {"data": {"viewer": None}},
        {"data": {"viewer": {"homes": None}}},
    ],
)
async def test_batch_handles_null_response_fields(mock_httpx_client, payload, caplog):
    """A nullable response should not generate an unexpected attribute error."""
    mock_httpx_client.post.return_value = _response(payload)
    api = TibberPublicAPI("test_token", mock_httpx_client)

    assert await api.get_all_homes_price_info() == {}
    assert "unexpected error" not in caplog.text


async def test_batch_skips_null_homes_and_preserves_prices(mock_httpx_client):
    """A null home should not discard another home's available prices."""
    mock_httpx_client.post.return_value = _response(
        {
            "data": {
                "viewer": {
                    "homes": [
                        None,
                        {
                            "id": "home1",
                            "currentSubscription": {
                                "priceInfo": {"today": [{"total": 0.5}]}
                            },
                        },
                    ]
                }
            }
        }
    )
    api = TibberPublicAPI("test_token", mock_httpx_client)

    assert await api.get_all_homes_price_info() == {
        "home1": {"today": [{"total": 0.5}]}
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"data": None},
        {"data": {"viewer": None}},
        {"data": {"viewer": {"home": None}}},
        {"data": {"viewer": {"home": {"currentSubscription": {"priceInfo": None}}}}},
    ],
)
async def test_fallback_unavailable_prices_are_retried(
    mock_httpx_client, payload, caplog
):
    """Unavailable data must not become a six-hour cached missing subscription."""
    mock_httpx_client.post.side_effect = [
        _response({"data": {"viewer": {"homes": []}}}),
        _response(payload),
        _response(
            {
                "data": {
                    "viewer": {
                        "homes": [
                            {
                                "id": "home1",
                                "currentSubscription": {
                                    "priceInfo": {"today": [{"total": 0.5}]}
                                },
                            }
                        ]
                    }
                }
            }
        ),
    ]
    api = TibberPublicAPI("test_token", mock_httpx_client)

    assert await api.get_price_info("home1") is None
    assert await api.get_price_info("home1") == {"today": [{"total": 0.5}]}
    assert "unexpected error" not in caplog.text


async def test_fallback_missing_subscription_is_negatively_cached(mock_httpx_client):
    """A successful fallback confirming no subscription may be cached."""
    mock_httpx_client.post.side_effect = [
        _response({"data": {"viewer": {"homes": []}}}),
        _response({"data": {"viewer": {"home": {"currentSubscription": None}}}}),
    ]
    api = TibberPublicAPI("test_token", mock_httpx_client)

    assert await api.get_price_info("home1") is None
    assert await api.get_price_info("home1") is None
    assert mock_httpx_client.post.call_count == 2


@pytest.mark.parametrize(
    "method", ["get_homes", "get_all_homes_price_info", "get_price_info"]
)
@pytest.mark.parametrize("status_code", [401, 403])
async def test_public_api_http_auth_errors(mock_httpx_client, method, status_code):
    """HTTP authentication failures must reach callers as authentication errors."""
    mock_httpx_client.post.return_value = _response({}, status_code)
    api = TibberPublicAPI("test_token", mock_httpx_client)
    arguments = ("home1",) if method == "get_price_info" else ()

    with pytest.raises(TibberPublicAuthError):
        await getattr(api, method)(*arguments)


@pytest.mark.parametrize(
    "method", ["get_homes", "get_all_homes_price_info", "get_price_info"]
)
@pytest.mark.parametrize("code", ["UNAUTHENTICATED", "FORBIDDEN"])
async def test_public_api_graphql_auth_errors(mock_httpx_client, method, code):
    """HTTP 200 GraphQL authentication errors must reach callers."""
    mock_httpx_client.post.return_value = _response(
        {
            "data": None,
            "errors": [{"message": "Access denied", "extensions": {"code": code}}],
        }
    )
    api = TibberPublicAPI("test_token", mock_httpx_client)
    arguments = ("home1",) if method == "get_price_info" else ()

    with pytest.raises(TibberPublicAuthError):
        await getattr(api, method)(*arguments)


async def test_fallback_graphql_auth_errors_are_not_swallowed(mock_httpx_client):
    """The fallback exception handler must preserve authentication failures."""
    mock_httpx_client.post.side_effect = [
        _response({"data": {"viewer": {"homes": []}}}),
        _response(
            {
                "data": None,
                "errors": [
                    {
                        "message": "Access denied",
                        "extensions": {"code": "UNAUTHENTICATED"},
                    }
                ],
            }
        ),
    ]
    api = TibberPublicAPI("test_token", mock_httpx_client)

    with pytest.raises(TibberPublicAuthError):
        await api.get_price_info("home1")


async def test_batch_graphql_failure_is_not_negatively_cached(
    mock_httpx_client, caplog
):
    """A resolver failure must be retried while valid partial data stays usable."""
    mock_httpx_client.post.side_effect = [
        _response(
            {
                "data": {
                    "viewer": {
                        "homes": [
                            {"id": "home1", "currentSubscription": None},
                            {
                                "id": "home2",
                                "currentSubscription": {
                                    "priceInfo": {"today": [{"total": 0.5}]}
                                },
                            },
                        ]
                    }
                },
                "errors": [
                    {
                        "message": "Subscription resolver unavailable",
                        "path": ["viewer", "homes", 0, "currentSubscription"],
                    }
                ],
            }
        ),
        _response(
            {
                "data": {
                    "viewer": {
                        "homes": [
                            {
                                "id": "home1",
                                "currentSubscription": {
                                    "priceInfo": {"today": [{"total": 0.9}]}
                                },
                            }
                        ]
                    }
                }
            }
        ),
    ]
    api = TibberPublicAPI("test_token", mock_httpx_client)

    assert await api.get_all_homes_price_info() == {
        "home2": {"today": [{"total": 0.5}]}
    }
    assert await api.get_price_info("home1") == {"today": [{"total": 0.9}]}
    assert await api.get_price_info("home2") == {"today": [{"total": 0.5}]}
    assert "Subscription resolver unavailable" in caplog.text
    assert "unexpected error" not in caplog.text


async def test_fallback_graphql_failure_is_not_negatively_cached(
    mock_httpx_client, caplog
):
    """GraphQL errors with a null subscription must not be cached as absence."""
    mock_httpx_client.post.side_effect = [
        _response({"data": {"viewer": {"homes": []}}}),
        _response(
            {
                "data": {"viewer": {"home": {"currentSubscription": None}}},
                "errors": [{"message": "Subscription resolver unavailable"}],
            }
        ),
        _response(
            {
                "data": {
                    "viewer": {
                        "homes": [
                            {
                                "id": "home1",
                                "currentSubscription": {
                                    "priceInfo": {"today": [{"total": 0.9}]}
                                },
                            }
                        ]
                    }
                }
            }
        ),
    ]
    api = TibberPublicAPI("test_token", mock_httpx_client)

    assert await api.get_price_info("home1") is None
    assert await api.get_price_info("home1") == {"today": [{"total": 0.9}]}
    assert "Subscription resolver unavailable" in caplog.text
    assert "unexpected error" not in caplog.text


async def test_get_homes_graphql_errors_are_reported(mock_httpx_client):
    """Home discovery must expose an API failure rather than empty success."""
    mock_httpx_client.post.return_value = _response(
        {"errors": [{"message": "Home resolver unavailable"}]}
    )
    api = TibberPublicAPI("test_token", mock_httpx_client)

    with pytest.raises(TibberPublicException, match="Home resolver unavailable"):
        await api.get_homes()


@pytest.mark.parametrize("cached_price", [None, {"today": [{"total": 0.1}]}])
async def test_expired_cache_does_not_hide_batch_failure(
    mock_httpx_client, cached_price
):
    """A failed refresh must fall back instead of returning expired cache data."""
    mock_httpx_client.post.side_effect = [
        _response({}, 503),
        _response(
            {
                "data": {
                    "viewer": {
                        "home": {
                            "currentSubscription": {
                                "priceInfo": {"today": [{"total": 0.9}]}
                            }
                        }
                    }
                }
            }
        ),
    ]
    api = TibberPublicAPI("test_token", mock_httpx_client)
    api._price_cache["home1"] = cached_price
    api._price_cache_time["home1"] = datetime.now(UTC) - timedelta(hours=7)

    assert await api.get_price_info("home1") == {"today": [{"total": 0.9}]}
