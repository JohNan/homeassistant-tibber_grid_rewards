"""Account hub managing shared connections, WebSocket multiplexing, and lifecycle per Tibber account."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .client import TibberAPI
from .public_client import TibberPublicAPI

_LOGGER = logging.getLogger(__name__)


class TibberAccountHub:
    """Shared hub for a Tibber user account managing unified resources."""

    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        api: TibberAPI,
        public_api: TibberPublicAPI | None = None,
    ) -> None:
        """Initialize the account hub."""
        self.hass = hass
        self.username = username
        self.api = api
        self.public_api = public_api
        self.entries: dict[str, ConfigEntry] = {}
        self._home_callbacks: dict[str, Callable[[dict[str, Any]], None]] = {}
        self._vehicle_callbacks: dict[
            str, dict[str, Callable[[dict[str, Any]], None]]
        ] = {}
        self._ws_task: asyncio.Task | None = None

    def get_active_targets(self) -> tuple[set[str], set[str]]:
        """Return the current set of active home_ids and vehicle_ids to subscribe to."""
        homes: set[str] = set()
        vehicles: set[str] = set()
        for entry in self.entries.values():
            home_id = entry.data.get("home_id")
            if home_id:
                homes.add(home_id)
            for device in entry.data.get("flex_devices", []):
                if device.get("type") == "vehicle" and "id" in device:
                    vehicles.add(device["id"])
        return homes, vehicles

    def register_home(
        self,
        entry: ConfigEntry,
        grid_reward_cb: Callable[[dict[str, Any]], None],
        vehicle_cbs: dict[str, Callable[[dict[str, Any]], None]],
    ) -> None:
        """Register an entry and its callbacks with the hub and ensure WebSocket is running."""
        self.entries[entry.entry_id] = entry
        home_id = entry.data.get("home_id")
        self._home_callbacks[entry.entry_id] = grid_reward_cb
        if home_id:
            self.api.register_grid_reward_callback(grid_reward_cb, home_id=home_id)

        self._vehicle_callbacks[entry.entry_id] = vehicle_cbs
        for vehicle_id, cb in vehicle_cbs.items():
            self.api.register_vehicle_callback(vehicle_id, cb)

        self._ensure_websocket()
        self.api.trigger_subscription_refresh()

    def unregister_home(self, entry_id: str) -> None:
        """Unregister an entry when unloaded."""
        entry = self.entries.pop(entry_id, None)
        if not entry:
            return

        home_id = entry.data.get("home_id")
        cb = self._home_callbacks.pop(entry_id, None)
        if cb and home_id:
            self.api.unregister_grid_reward_callback(cb, home_id=home_id)

        veh_cbs = self._vehicle_callbacks.pop(entry_id, {})
        for vehicle_id, vcb in veh_cbs.items():
            self.api.unregister_vehicle_callback(vehicle_id, vcb)

        self.api.trigger_subscription_refresh()

    def has_entries(self) -> bool:
        """Check if any entries remain attached to this hub."""
        return bool(self.entries)

    def _ensure_websocket(self) -> None:
        """Ensure the single background WebSocket task is running."""
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = self.hass.async_create_background_task(
                self.api.run_multiplexed_subscription(self.get_active_targets),
                name=f"tibber-ws-hub-{self.username}",
            )

    async def async_close(self) -> None:
        """Close the WebSocket and cancel the task."""
        await self.api.async_close_websocket()
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ws_task
            self._ws_task = None
