"""DataUpdateCoordinator for Tibber Grid Reward query blocks and devices."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .battery_blocks import create_battery_query_composer
from .client import TibberAPI, TibberConnectionError, TibberException
from .query_blocks import GraphQLQueryBlock, GraphQLQueryComposer, create_query_composer

_LOGGER = logging.getLogger(__name__)

BATTERY_UPDATE_INTERVAL = timedelta(minutes=5)


class TibberBlockData:
    """Class representing consolidated query block telemetry.

    Pre-made battery blocks are stored and accessed identically to any
    custom or generic query block.
    """

    def __init__(
        self,
        data: dict[str, Any] | None = None,
        *,
        savings: dict[str, Any] | None = None,
        activity: list[dict[str, Any]] | None = None,
        planned: list[dict[str, Any]] | None = None,
        extra: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if isinstance(data, TibberBlockData):
            self._data: dict[str, Any] = dict(data._data)
        elif data is not None:
            self._data = dict(data)
        else:
            self._data = {}

        if savings is not None:
            self._data["savings"] = savings
        if activity is not None:
            self._data["activity"] = activity
        if planned is not None:
            self._data["planned"] = planned
        if extra:
            self._data.update(extra)
        if kwargs:
            self._data.update(kwargs)

    @property
    def savings(self) -> dict[str, Any]:
        """Return parsed savings data (pre-made block 'savings')."""
        return self._data.get("savings", {})

    @property
    def activity(self) -> list[dict[str, Any]]:
        """Return parsed activity data (pre-made block 'activity')."""
        return self._data.get("activity", [])

    @property
    def planned(self) -> list[dict[str, Any]]:
        """Return parsed planned data (pre-made block 'planned')."""
        return self._data.get("planned", [])

    @property
    def extra(self) -> dict[str, Any]:
        """Backward compatibility mapping for non-default block data."""
        standard_keys = {"savings", "activity", "planned"}
        return {k: v for k, v in self._data.items() if k not in standard_keys}

    def get(self, block_name: str, default: Any = None) -> Any:
        """Return parsed telemetry for any modular block by name."""
        return self._data.get(block_name, default)

    def __getitem__(self, item: str) -> Any:
        """Allow dict-like subscription for any block data."""
        return self._data[item]

    def __contains__(self, item: str) -> bool:
        """Allow membership checks for block names."""
        return item in self._data

    def __iter__(self):
        """Iterate over block names."""
        return iter(self._data)

    def __len__(self) -> int:
        """Return number of registered block results."""
        return len(self._data)

    def __getattr__(self, name: str) -> Any:
        """Allow direct attribute access for any block name."""
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._data:
            return self._data[name]
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    def __bool__(self) -> bool:
        return bool(self._data)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, TibberBlockData):
            return self._data == other._data
        if isinstance(other, dict):
            return self._data == other
        return False

    def __repr__(self) -> str:
        return f"TibberBlockData({self._data!r})"


# Backward compatibility aliases
TibberBatteryData = TibberBlockData
TibberQueryData = TibberBlockData


class TibberQueryDataCoordinator(DataUpdateCoordinator[TibberBlockData]):
    """Coordinator to manage fetching query block data in a single consolidated API call."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: TibberAPI,
        home_id: str,
        device_id: str | None = None,
        update_interval: timedelta = BATTERY_UPDATE_INTERVAL,
        composer: GraphQLQueryComposer
        | Sequence[GraphQLQueryBlock | str]
        | None = None,
        name: str | None = None,
        *,
        battery_id: str | None = None,
        blocks: Sequence[GraphQLQueryBlock | str] | None = None,
        config_entry: Any = None,
    ) -> None:
        """Initialize the query block data coordinator."""
        effective_device_id = device_id or battery_id
        effective_name = name or (
            f"Tibber Battery {effective_device_id}"
            if effective_device_id
            else f"Tibber Home {home_id}"
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=effective_name,
            update_interval=update_interval,
        )
        self.api = api
        self.home_id = home_id
        self.device_id = effective_device_id
        self.battery_id = effective_device_id

        if isinstance(composer, GraphQLQueryComposer):
            self.composer: GraphQLQueryComposer = composer
        elif blocks is not None:
            self.composer = create_query_composer(blocks=blocks)
        elif isinstance(composer, (list, tuple, set)):
            self.composer = create_query_composer(blocks=composer)
        else:
            self.composer = create_battery_query_composer()

    async def _async_update_data(self) -> TibberBlockData:
        """Fetch telemetry details from Tibber API via query block composer."""
        try:
            raw = await self.api.execute_query_blocks(
                self.composer,
                self.home_id,
                device_id=self.device_id,
            )
            return TibberBlockData(raw)
        except (TibberConnectionError, TibberException) as err:
            raise UpdateFailed(f"Error communicating with Tibber API: {err}") from err
        except Exception as err:
            raise UpdateFailed(
                f"Unexpected error updating battery data: {err}"
            ) from err


# Backward compatibility alias
TibberBatteryDataCoordinator = TibberQueryDataCoordinator
