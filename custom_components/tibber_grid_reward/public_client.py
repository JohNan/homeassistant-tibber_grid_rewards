import logging
import httpx
from typing import Any, Dict, List

_LOGGER = logging.getLogger(__name__)

PUBLIC_API_URL = "https://api.tibber.com/v1-beta/gql"


class TibberPublicException(Exception):
    """Base exception for the Tibber public API client."""


class TibberPublicAuthError(TibberPublicException):
    """Exception for authentication errors."""


class TibberPublicAPI:
    """A client for the public Tibber API."""

    def __init__(self, token: str, client: httpx.AsyncClient):
        """Initialize the client."""
        self._token = token
        self._client = client
        self.headers = {
            "Authorization": f"Bearer {self._token}",
        }

    async def get_homes(self) -> List[Dict[str, Any]]:
        """Fetch Tibber homes."""
        _LOGGER.debug("Fetching Tibber homes from public API.")
        query = "{ viewer { homes { id appNickname address { address1 } } } }"
        payload = {"query": query}
        try:
            response = await self._client.post(
                PUBLIC_API_URL, headers=self.headers, json=payload
            )
            response.raise_for_status()
            _LOGGER.debug("Successfully fetched Tibber homes from public API.")
            homes = response.json().get("data", {}).get("viewer", {}).get("homes", [])
            for home in homes:
                home["title"] = home.get("appNickname") or (
                    home.get("address") or {}
                ).get("address1", home["id"])
            return homes
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                _LOGGER.error("Authentication failed with public API.")
                raise TibberPublicAuthError from e
            _LOGGER.error("Could not fetch homes from public API: %s", e)
            raise TibberPublicException from e
        except Exception as e:
            _LOGGER.error("An unexpected error occurred while fetching homes: %s", e)
            raise TibberPublicException from e

    async def get_price_info(self, home_id: str) -> Dict[str, Any] | None:
        """Fetch price info for a specific home."""
        _LOGGER.debug("Fetching price info for home %s from public API.", home_id)
        query = """
        query($homeId: ID!) {
          viewer {
            home(id: $homeId) {
              currentSubscription {
                priceInfo {
                  current {
                    total
                    energy
                    tax
                    startsAt
                  }
                  today {
                    total
                    energy
                    tax
                    startsAt
                  }
                  tomorrow {
                    total
                    energy
                    tax
                    startsAt
                  }
                }
              }
            }
          }
        }
        """
        payload = {"query": query, "variables": {"homeId": home_id}}
        try:
            response = await self._client.post(
                PUBLIC_API_URL, headers=self.headers, json=payload
            )
            response.raise_for_status()
            _LOGGER.debug("Successfully fetched price info from public API.")
            data = response.json()
            return data.get("data", {}).get("viewer", {}).get("home", {}).get(
                "currentSubscription", {}
            ).get("priceInfo")
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                _LOGGER.error("Authentication failed with public API.")
                raise TibberPublicAuthError from e
            _LOGGER.error("Could not fetch price info from public API: %s", e)
            return None
        except Exception as e:
            _LOGGER.error(
                "An unexpected error occurred while fetching price info: %s", e
            )
            return None