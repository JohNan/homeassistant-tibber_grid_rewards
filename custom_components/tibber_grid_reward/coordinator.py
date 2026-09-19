"""DataUpdateCoordinator for Tibber Grid Reward battery devices."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .battery_blocks import BatteryQueryComposer
from .client import TibberAPI, TibberConnectionError, TibberException

_LOGGER = logging.getLogger(__name__)

BATTERY_UPDATE_INTERVAL = timedelta(minutes=5)


@dataclass(slots=True)
class TibberBatteryData:
    """Class representing consolidated battery telemetry."""

    savings: dict[str, Any] = field(default_factory=dict)
    activity: list[dict[str, Any]] = field(default_factory=list)
    planned: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def get(self, block_name: str, default: Any = None) -> Any:
        """Return parsed telemetry for any modular block by name."""
        if hasattr(self, block_name) and block_name != "extra":
            return getattr(self, block_name)
        return self.extra.get(block_name, default)

    def __getitem__(self, item: str) -> Any:
        """Allow dict-like subscription for block data."""
        return self.get(item)


class TibberBatteryDataCoordinator(DataUpdateCoordinator[TibberBatteryData]):
    """Coordinator to manage fetching battery data in a single consolidated API call."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: TibberAPI,
        home_id: str,
        battery_id: str,
        update_interval: timedelta = BATTERY_UPDATE_INTERVAL,
        composer: BatteryQueryComposer | None = None,
    ) -> None:
        """Initialize the battery coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"Tibber Battery {battery_id}",
            update_interval=update_interval,
        )
        self.api = api
        self.home_id = home_id
        self.battery_id = battery_id
        self.composer = composer or BatteryQueryComposer()

    async def _async_update_data(self) -> TibberBatteryData:
        """Fetch battery details from Tibber API."""
        try:
            raw = await self.api.get_battery_details(
                self.home_id, self.battery_id, composer=self.composer
            )
            standard_keys = {"savings", "activity", "planned"}
            return TibberBatteryData(
                savings=raw.get("savings", {}),
                activity=raw.get("activity", []),
                planned=raw.get("planned", []),
                extra={k: v for k, v in raw.items() if k not in standard_keys},
            )
        except (TibberConnectionError, TibberException) as err:
            raise UpdateFailed(f"Error communicating with Tibber API: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error updating battery data: {err}") from err
