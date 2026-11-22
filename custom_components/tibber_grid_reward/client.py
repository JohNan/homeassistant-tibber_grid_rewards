from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import ssl
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt
import websockets

_LOGGER = logging.getLogger(__name__)

AUTH_URL = "https://app.tibber.com/v1/login.credentials"
GRAPHQL_WS_URL = "wss://app.tibber.com/v4/gql/ws"
GRAPHQL_URL = "https://app.tibber.com/v4/gql"


class TibberException(Exception):
    """Base exception for the Tibber API client."""


class TibberAuthError(TibberException):
    """Exception for authentication errors."""


class TibberConnectionError(TibberException):
    """Exception for connection errors."""


@dataclass
class _SubscriptionBackoff:
    """Per-target backoff state for subscriptions ended by the server."""

    failures: int = 0
    retry_at: float = 0.0
    warned: bool = False


class TibberAPI:
    SUBSCRIPTION_BACKOFF_INITIAL: float = 5.0
    SUBSCRIPTION_BACKOFF_MAX: float = 300.0
    SUBSCRIPTION_BACKOFF_FACTOR: float = 2.0
    SUBSCRIPTION_STABLE_SECONDS: float = 60.0
    SUBSCRIPTION_WARN_THRESHOLD: int = 3

    def __init__(self, username: str, password: str, client: httpx.AsyncClient):
        self.username: str = username
        self.password: str = password
        self._client: httpx.AsyncClient = client
        self._cached_token: str | None = None
        self._cached_exp: float = 0
        self._ws_reconnect: bool = True
        self._websocket: Any = None
        self._sub_callback: Callable[[dict[str, Any]], None] | None = None
        self._home_callbacks: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._vehicle_callbacks: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._sub_refresh_event: asyncio.Event = asyncio.Event()
        self._sub_backoff: dict[tuple[str, str], _SubscriptionBackoff] = {}
        self.home_id: str | None = None

    async def _get_ssl_context(self) -> ssl.SSLContext:
        """Get SSL context in a thread-safe way."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, ssl.create_default_context)

    async def close_websocket(self) -> None:
        self._ws_reconnect = False
        self._sub_refresh_event.set()
        if self._websocket is not None:
            await self._websocket.close()

    async def async_close_websocket(self) -> None:
        """Alias for close_websocket for consistency."""
        await self.close_websocket()

    async def fetch_token(self) -> str:
        now = time.time()
        if self._cached_token and (self._cached_exp - now > 30):
            return self._cached_token

        _LOGGER.debug("Fetching new Tibber token.")
        try:
            response = await self._client.post(
                AUTH_URL,
                json={"email": self.username, "password": self.password},
                timeout=10,
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            token: str = data.get("token")
            decoded: dict[str, Any] = jwt.decode(
                token, options={"verify_signature": False}
            )
            self._cached_exp = decoded.get("exp", 0)
            self._cached_token = token
            _LOGGER.debug("Successfully fetched new Tibber token.")
            return token
        except httpx.HTTPStatusError as e:
            raise TibberAuthError from e
        except Exception as e:
            raise TibberException from e

    async def get_homes(self) -> list[dict[str, Any]]:
        _LOGGER.debug("Fetching Tibber homes.")
        token = await self.fetch_token()
        headers = {"Authorization": f"Bearer {token}"}
        query = "{ me { homes { id title } } }"
        try:
            response = await self._client.post(
                GRAPHQL_URL, headers=headers, json={"query": query}
            )
            response.raise_for_status()
            _LOGGER.debug("Successfully fetched Tibber homes.")
            return response.json().get("data", {}).get("me", {}).get("homes", [])
        except httpx.HTTPStatusError as e:
            raise TibberConnectionError from e
        except Exception as e:
            raise TibberException from e

    async def get_battery_details(
        self,
        home_id: str,
        battery_id: str,
        activity_hours_back: int = 6,
        days_ahead: int = 1,
        composer: Any | None = None,
    ) -> dict[str, Any]:
        """Fetch battery savings, activity history, and planned timeline in one query.

        Pre-made battery blocks are executed through the generic execute_query_blocks engine.
        """
        _LOGGER.debug("Fetching combined battery details for battery %s", battery_id)
        if composer is None:
            from .battery_blocks import (
                BatteryActivityBlock,
                BatteryPlannedBlock,
                BatteryQueryComposer,
                BatterySavingsBlock,
            )

            composer = BatteryQueryComposer(
                [
                    BatterySavingsBlock(),
                    BatteryActivityBlock(hours_back=activity_hours_back),
                    BatteryPlannedBlock(days_ahead=days_ahead),
                ]
            )

        return await self.execute_query_blocks(
            composer=composer,
            home_id=home_id,
            device_id=battery_id,
        )

    async def execute_query_blocks(
        self,
        composer: Any,
        home_id: str,
        device_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute arbitrary modular GraphQL queries composed via GraphQLQueryComposer or sequence of blocks."""
        from .query_blocks import GraphQLQueryComposer

        if hasattr(composer, "build_query") and hasattr(composer, "parse_response"):
            comp = composer
        elif isinstance(composer, (list, tuple, set)):
            comp = GraphQLQueryComposer(blocks=composer)
        else:
            comp = GraphQLQueryComposer(blocks=[composer])

        token = await self.fetch_token()
        headers = {"Authorization": f"Bearer {token}"}
        now = datetime.now(UTC)

        query = comp.build_query()
        variables = comp.build_variables(now, home_id, device_id=device_id, **kwargs)

        payload = {
            "operationName": comp.operation_name,
            "variables": variables,
            "query": query,
        }
        try:
            response = await self._client.post(
                GRAPHQL_URL, headers=headers, json=payload
            )
            response.raise_for_status()
            res_json = response.json()
            if res_json.get("errors") and not res_json.get("data"):
                raise TibberException(
                    f"GraphQL error executing query blocks: {res_json.get('errors')}"
                )
            data = res_json.get("data") or {}
        except httpx.HTTPStatusError as e:
            raise TibberConnectionError from e
        except TibberException:
            raise
        except Exception as e:
            raise TibberException from e

        return comp.parse_response(data)

    async def execute_block(
        self,
        block: Any,
        home_id: str,
        device_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute a single modular GraphQL query block and return its parsed output directly."""
        res = await self.execute_query_blocks(
            composer=[block],
            home_id=home_id,
            device_id=device_id,
            **kwargs,
        )
        return next(iter(res.values())) if res else None

    async def get_battery_savings(
        self, home_id: str, battery_id: str
    ) -> dict[str, Any]:
        """Fetch aggregated battery savings (kept for backwards compatibility)."""
        details = await self.get_battery_details(home_id, battery_id)
        return details.get("savings", {})

    async def set_smart_charging_enabled(
        self, home_id: str, vehicle_id: str, enabled: bool
    ) -> None:
        _LOGGER.debug(
            "Setting smart charging enabled to %s for vehicle %s", enabled, vehicle_id
        )
        token = await self.fetch_token()
        headers = {"Authorization": f"Bearer {token}"}
        payload_online = {
            "operationName": "SetVehicleSettings",
            "variables": {
                "vehicleId": vehicle_id,
                "homeId": home_id,
                "settings": [
                    {"key": "online.vehicle.smartCharging.isEnabled", "value": enabled}
                ],
            },
            "query": """
            mutation SetVehicleSettings($vehicleId: String!, $homeId: String!, $settings: [SettingsItemInput!]) {
              me {
                setVehicleSettings(id: $vehicleId, homeId: $homeId, settings: $settings) {
                  __typename
                }
              }
            }
            """,
        }
        try:
            response = await self._client.post(
                GRAPHQL_URL, headers=headers, json=payload_online
            )
            response.raise_for_status()
            res_json = response.json()
            if res_json.get("errors"):
                # If online setting key fails (e.g., offline vehicle), attempt offline setting key
                payload_offline = {
                    "operationName": "SetVehicleSettings",
                    "variables": {
                        "vehicleId": vehicle_id,
                        "homeId": home_id,
                        "settings": [
                            {
                                "key": "offline.vehicle.smartCharging.isEnabled",
                                "value": enabled,
                            }
                        ],
                    },
                    "query": payload_online["query"],
                }
                response_offline = await self._client.post(
                    GRAPHQL_URL, headers=headers, json=payload_offline
                )
                response_offline.raise_for_status()
                if errors := response_offline.json().get("errors"):
                    raise TibberException(
                        f"Failed to set smart charging for vehicle {vehicle_id}: {errors}"
                    )
            _LOGGER.debug("Successfully updated smart charging setting.")
        except httpx.HTTPStatusError as e:
            raise TibberConnectionError from e
        except TibberException:
            raise
        except Exception as e:
            raise TibberException from e

    async def validate_grid_reward(self, home_id: str) -> dict[str, Any] | None:
        _LOGGER.debug("Validating grid reward for home: %s", home_id)
        token = await self.fetch_token()
        headers = {"Authorization": f"Bearer {token}"}

        try:
            ssl_context = await self._get_ssl_context()
            async with websockets.connect(
                GRAPHQL_WS_URL,
                additional_headers=headers,
                subprotocols=["graphql-transport-ws"],
                ssl=ssl_context,
            ) as websocket:
                await websocket.send(json.dumps({"type": "connection_init"}))
                msg = await asyncio.wait_for(websocket.recv(), timeout=10)
                if json.loads(msg).get("type") != "connection_ack":
                    raise TibberConnectionError("Connection ACK not received.")

                subscribe_msg = self._build_grid_reward_subscribe_message(home_id, "1")
                await websocket.send(json.dumps(subscribe_msg))
                msg = await asyncio.wait_for(websocket.recv(), timeout=10)
                data: dict[str, Any] = json.loads(msg)

                if data.get("type") == "next":
                    _LOGGER.debug("Successfully validated grid reward.")
                    return (
                        data.get("payload", {}).get("data", {}).get("gridRewardStatus")
                    )
                return None
        except (TimeoutError, websockets.exceptions.WebSocketException) as e:
            raise TibberConnectionError from e
        except Exception as e:
            raise TibberException from e

    def register_grid_reward_callback(
        self, callback: Callable[[dict[str, Any]], None], home_id: str | None = None
    ) -> None:
        """Register a callback for grid reward updates, optionally scoped to a home_id."""
        if home_id:
            cbs = self._home_callbacks.setdefault(home_id, [])
            if callback not in cbs:
                cbs.append(callback)
        else:
            self._sub_callback = callback

    def unregister_grid_reward_callback(
        self, callback: Callable[[dict[str, Any]], None], home_id: str | None = None
    ) -> None:
        """Unregister a grid reward callback."""
        if home_id and home_id in self._home_callbacks:
            if callback in self._home_callbacks[home_id]:
                self._home_callbacks[home_id].remove(callback)
            if not self._home_callbacks[home_id]:
                del self._home_callbacks[home_id]
        else:
            for hid, cbs in list(self._home_callbacks.items()):
                if callback in cbs:
                    cbs.remove(callback)
                if not cbs:
                    del self._home_callbacks[hid]
        if self._sub_callback == callback:
            self._sub_callback = None

    def register_vehicle_callback(
        self, vehicle_id: str, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        """Register a callback for a vehicle."""
        cbs = self._vehicle_callbacks.setdefault(vehicle_id, [])
        if callback not in cbs:
            cbs.append(callback)

    def unregister_vehicle_callback(
        self, vehicle_id: str, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        """Unregister a vehicle callback."""
        if vehicle_id in self._vehicle_callbacks:
            if callback in self._vehicle_callbacks[vehicle_id]:
                self._vehicle_callbacks[vehicle_id].remove(callback)
            if not self._vehicle_callbacks[vehicle_id]:
                del self._vehicle_callbacks[vehicle_id]

    def trigger_subscription_refresh(self) -> None:
        """Signal that active subscription targets have changed."""
        self._sub_refresh_event.set()

    def _dispatch_grid_reward(
        self, reward_data: dict[str, Any], home_id: str | None = None
    ) -> None:
        """Dispatch grid reward data to registered callbacks."""
        if not home_id:
            home_id = reward_data.get("homeId") or self.home_id

        callbacks_to_call: list[Callable[[dict[str, Any]], None]] = []
        if home_id and home_id in self._home_callbacks:
            callbacks_to_call.extend(self._home_callbacks[home_id])
        elif self._sub_callback:
            callbacks_to_call.append(self._sub_callback)

        for cb in callbacks_to_call:
            try:
                cb(reward_data)
            except Exception:
                _LOGGER.exception("Error in grid reward callback for home %s", home_id)

    def _dispatch_vehicle_state(
        self, vehicle_id: str, vehicle_data: dict[str, Any]
    ) -> None:
        """Dispatch vehicle state data to registered callbacks."""
        callbacks = list(self._vehicle_callbacks.get(vehicle_id, []))
        for cb in callbacks:
            try:
                cb(vehicle_data)
            except Exception:
                _LOGGER.exception(
                    "Error in vehicle callback for vehicle %s", vehicle_id
                )

    def _get_next_retry_timeout(
        self, is_connected: bool, target_map: dict[tuple[str, str], str]
    ) -> float | None:
        """Return seconds until the earliest pending backoff retry, or None."""
        if not is_connected or not self._sub_backoff:
            return None
        earliest = min(
            (
                backoff.retry_at
                for target, backoff in self._sub_backoff.items()
                if target not in target_map and backoff.retry_at > 0.0
            ),
            default=None,
        )
        if earliest is None:
            return None
        return max(0.0, earliest - time.monotonic())

    def _has_due_retry(self, target_map: dict[tuple[str, str], str]) -> bool:
        """Return True if any backed-off target is now due for retry."""
        if not self._sub_backoff:
            return False
        now = time.monotonic()
        return any(
            target not in target_map and 0.0 < backoff.retry_at <= now
            for target, backoff in self._sub_backoff.items()
        )

    def _clear_stable_backoffs(
        self,
        sub_map: dict[str, tuple[str, str]],
        sub_started_at: dict[str, float],
    ) -> None:
        """Clear backoff state for subscriptions that stayed open long enough."""
        now = time.monotonic()
        for sub_id, target in sub_map.items():
            started_at = sub_started_at.get(sub_id)
            if (
                started_at is not None
                and (now - started_at) >= self.SUBSCRIPTION_STABLE_SECONDS
            ):
                self._sub_backoff.pop(target, None)

    def _handle_next_message(
        self,
        data: dict[str, Any],
        sub_map: dict[str, tuple[str, str]],
        sub_started_at: dict[str, float],
    ) -> None:
        """Process an incoming GraphQL transport `next` message."""
        sub_id = data.get("id")
        raw_payload = data.get("payload")
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        raw_data = payload.get("data")
        payload_data = raw_data if isinstance(raw_data, dict) else {}
        sub_info = sub_map.get(sub_id) if sub_id is not None else None

        if errors := payload.get("errors"):
            _LOGGER.warning(
                "Multiplexed subscription payload errors for %s: %s",
                sub_info or sub_id,
                errors,
            )

        dispatched = False
        if "gridRewardStatus" in payload_data:
            reward_data = payload_data["gridRewardStatus"]
            if reward_data:
                home_id = reward_data.get("homeId") or (
                    sub_info[1] if sub_info else None
                )
                self._dispatch_grid_reward(reward_data, home_id)
                dispatched = True
        elif "vehicleState" in payload_data:
            vehicle_data = payload_data["vehicleState"]
            if vehicle_data:
                vehicle_id = vehicle_data.get("id") or (
                    sub_info[1] if sub_info else None
                )
                if vehicle_id:
                    self._dispatch_vehicle_state(vehicle_id, vehicle_data)
                    dispatched = True

        if dispatched and sub_info is not None and sub_id is not None:
            started_at = sub_started_at.get(sub_id)
            backoff = self._sub_backoff.get(sub_info)
            if (
                backoff is not None
                and started_at is not None
                and (time.monotonic() - started_at) >= self.SUBSCRIPTION_STABLE_SECONDS
            ):
                if backoff.warned:
                    _LOGGER.info(
                        "Subscription for %s target %s recovered.",
                        sub_info[0],
                        sub_info[1],
                    )
                del self._sub_backoff[sub_info]

    def _handle_subscription_ended(
        self,
        sub_id: str | None,
        reason: str,
        sub_map: dict[str, tuple[str, str]],
        target_map: dict[tuple[str, str], str],
        sub_started_at: dict[str, float],
        error_payload: Any = None,
    ) -> None:
        """Handle server-initiated subscription termination with per-target backoff."""
        sub_info = sub_map.pop(sub_id, None) if sub_id is not None else None
        started_at = sub_started_at.pop(sub_id, None) if sub_id is not None else None
        if sub_info is None:
            if reason == "error":
                _LOGGER.error(
                    "Multiplexed subscription error for unknown subscription %s: %s",
                    sub_id,
                    error_payload,
                )
            return

        if target_map.get(sub_info) == sub_id:
            del target_map[sub_info]

        now = time.monotonic()
        backoff = self._sub_backoff.get(sub_info)
        if (
            started_at is not None
            and (now - started_at) >= self.SUBSCRIPTION_STABLE_SECONDS
        ) or backoff is None:
            backoff = _SubscriptionBackoff()
            self._sub_backoff[sub_info] = backoff

        backoff.failures += 1
        exponent = min(backoff.failures - 1, 30)
        try:
            delay = min(
                self.SUBSCRIPTION_BACKOFF_INITIAL
                * (self.SUBSCRIPTION_BACKOFF_FACTOR**exponent),
                self.SUBSCRIPTION_BACKOFF_MAX,
            )
        except OverflowError:
            delay = self.SUBSCRIPTION_BACKOFF_MAX
        delay = max(0.0, delay)
        backoff.retry_at = now + delay

        kind, target_id = sub_info
        if reason == "error":
            if backoff.failures == 1:
                _LOGGER.error(
                    "Multiplexed subscription error for %s target %s (id=%s): %s; retrying in %.0fs",
                    kind,
                    target_id,
                    sub_id,
                    error_payload,
                    delay,
                )
            elif (
                not backoff.warned
                and backoff.failures >= self.SUBSCRIPTION_WARN_THRESHOLD
            ):
                backoff.warned = True
                _LOGGER.warning(
                    "Multiplexed subscription for %s target %s failed with errors %d consecutive times (%s); backing off up to %.0fs",
                    kind,
                    target_id,
                    backoff.failures,
                    error_payload,
                    self.SUBSCRIPTION_BACKOFF_MAX,
                )
            else:
                _LOGGER.debug(
                    "Multiplexed subscription error for %s target %s (id=%s): %s; retrying in %.0fs (attempt %d)",
                    kind,
                    target_id,
                    sub_id,
                    error_payload,
                    delay,
                    backoff.failures,
                )
        elif (
            not backoff.warned and backoff.failures >= self.SUBSCRIPTION_WARN_THRESHOLD
        ):
            backoff.warned = True
            _LOGGER.warning(
                "Subscription for %s target %s repeatedly completed by server (%d consecutive times); backing off up to %.0fs. If this device was removed or re-added in Tibber, reconfigure the integration",
                kind,
                target_id,
                backoff.failures,
                self.SUBSCRIPTION_BACKOFF_MAX,
            )
        else:
            _LOGGER.debug(
                "Subscription for %s target %s ended (%s); retrying in %.0fs (attempt %d)",
                kind,
                target_id,
                reason,
                delay,
                backoff.failures,
            )

    async def _sync_targets(
        self,
        websocket: Any,
        sub_map: dict[str, tuple[str, str]],
        target_map: dict[tuple[str, str], str],
        sub_started_at: dict[str, float],
        get_active_targets: Callable[[], tuple[set[str], set[str]]],
    ) -> None:
        """Synchronize active subscriptions with the desired set of targets."""
        active_homes, active_vehicles = get_active_targets()
        wanted = {("home", h) for h in active_homes} | {
            ("vehicle", v) for v in active_vehicles
        }
        for target in list(self._sub_backoff):
            if target not in wanted:
                del self._sub_backoff[target]

        current = set(target_map.keys())
        now = time.monotonic()

        # Subscribe new targets
        for kind, target_id in wanted - current:
            target = (kind, target_id)
            backoff = self._sub_backoff.get(target)
            if backoff is not None and backoff.retry_at > now:
                continue
            if backoff is not None:
                backoff.retry_at = 0.0

            sub_id = str(uuid.uuid4())
            sub_map[sub_id] = target
            target_map[target] = sub_id
            sub_started_at[sub_id] = now
            if kind == "home":
                msg = self._build_grid_reward_subscribe_message(target_id, sub_id)
            else:
                msg = self._build_vehicle_state_subscribe_message(target_id, sub_id)
            _LOGGER.debug(
                "Subscribing %s target %s with id %s",
                kind,
                target_id,
                sub_id,
            )
            await websocket.send(json.dumps(msg))

        # Unsubscribe removed targets
        for kind, target_id in current - wanted:
            sub_id = target_map.pop((kind, target_id))
            sub_map.pop(sub_id, None)
            sub_started_at.pop(sub_id, None)
            _LOGGER.debug(
                "Unsubscribing %s target %s with id %s",
                kind,
                target_id,
                sub_id,
            )
            await websocket.send(json.dumps({"type": "complete", "id": sub_id}))

    async def run_multiplexed_subscription(
        self, get_active_targets: Callable[[], tuple[set[str], set[str]]]
    ) -> None:
        """Run a single multiplexed websocket connection handling all homes and vehicles."""
        self._ws_reconnect = True
        self._sub_backoff.clear()
        _LOGGER.info("Starting multiplexed Tibber websocket subscription.")
        try:
            while self._ws_reconnect:
                recv_task: asyncio.Task[Any] | None = None
                refresh_waiter: asyncio.Task[Any] | None = None
                sub_map: dict[str, tuple[str, str]] = {}
                sub_started_at: dict[str, float] = {}
                try:
                    token = await self.fetch_token()
                    headers = {"Authorization": f"Bearer {token}"}
                    ssl_context = await self._get_ssl_context()
                    async with websockets.connect(
                        GRAPHQL_WS_URL,
                        additional_headers=headers,
                        subprotocols=["graphql-transport-ws"],
                        ssl=ssl_context,
                    ) as websocket:
                        self._websocket = websocket
                        await websocket.send(json.dumps({"type": "connection_init"}))

                        target_map: dict[tuple[str, str], str] = {}
                        is_connected = False

                        while self._ws_reconnect:
                            if recv_task is None:
                                recv_task = asyncio.create_task(websocket.recv())

                            refresh_waiter = asyncio.create_task(
                                self._sub_refresh_event.wait()
                            )
                            timeout = self._get_next_retry_timeout(
                                is_connected, target_map
                            )
                            done, _ = await asyncio.wait(
                                [recv_task, refresh_waiter],
                                timeout=timeout,
                                return_when=asyncio.FIRST_COMPLETED,
                            )

                            if not self._ws_reconnect:
                                break

                            should_sync = False
                            if refresh_waiter in done:
                                self._sub_refresh_event.clear()
                                refresh_waiter = None
                                should_sync = True
                            else:
                                refresh_waiter.cancel()
                                with contextlib.suppress(asyncio.CancelledError):
                                    await refresh_waiter
                                refresh_waiter = None
                                if not done:
                                    should_sync = True

                            if recv_task in done:
                                msg = recv_task.result()
                                recv_task = None
                                data: dict[str, Any] = json.loads(msg)
                                msg_type = data.get("type")

                                if msg_type == "connection_ack":
                                    _LOGGER.debug(
                                        "Multiplexed websocket connection acknowledged."
                                    )
                                    is_connected = True
                                    should_sync = True
                                elif msg_type == "ping":
                                    await websocket.send(json.dumps({"type": "pong"}))
                                elif msg_type == "next":
                                    self._handle_next_message(
                                        data, sub_map, sub_started_at
                                    )
                                elif msg_type == "complete":
                                    self._handle_subscription_ended(
                                        data.get("id"),
                                        "complete",
                                        sub_map,
                                        target_map,
                                        sub_started_at,
                                    )
                                elif msg_type == "error":
                                    self._handle_subscription_ended(
                                        data.get("id"),
                                        "error",
                                        sub_map,
                                        target_map,
                                        sub_started_at,
                                        error_payload=data.get("payload"),
                                    )

                            if is_connected and (
                                should_sync or self._has_due_retry(target_map)
                            ):
                                await self._sync_targets(
                                    websocket,
                                    sub_map,
                                    target_map,
                                    sub_started_at,
                                    get_active_targets,
                                )
                except (
                    websockets.exceptions.ConnectionClosedError,
                    websockets.exceptions.ConnectionClosedOK,
                ):
                    if not self._ws_reconnect:
                        break
                    _LOGGER.warning(
                        "Websocket connection closed, reconnecting in 5 seconds."
                    )
                except Exception:
                    _LOGGER.exception(
                        "Error in websocket subscription, reconnecting in 5 seconds."
                    )
                finally:
                    self._clear_stable_backoffs(sub_map, sub_started_at)
                    self._websocket = None
                    for task in (recv_task, refresh_waiter):
                        if task is None:
                            continue
                        if not task.done():
                            task.cancel()
                            with contextlib.suppress(asyncio.CancelledError, Exception):
                                await task
                        elif not task.cancelled():
                            task.exception()

                if self._ws_reconnect:
                    await asyncio.sleep(5)
        except asyncio.CancelledError:
            _LOGGER.info("Multiplexed websocket subscription task cancelled.")
            raise

    async def subscribe_grid_reward(self, home_id: str) -> None:
        """Backward-compatible wrapper to subscribe to grid reward updates."""
        self.home_id = home_id
        await self.run_multiplexed_subscription(lambda: ({home_id}, set()))

    async def subscribe_vehicle_state(self, vehicle_id: str) -> None:
        """Backward-compatible wrapper to subscribe to vehicle state updates."""
        await self.run_multiplexed_subscription(lambda: (set(), {vehicle_id}))

    def _build_grid_reward_subscribe_message(
        self, home_id: str, sub_id: str
    ) -> dict[str, Any]:
        return {
            "type": "subscribe",
            "id": sub_id,
            "payload": {
                "operationName": "gridRewardsSubscription",
                "variables": {"homeId": home_id},
                "query": """
                subscription gridRewardsSubscription($homeId: String!) {
                  gridRewardStatus(homeId: $homeId) {
                    __typename
                    ...gridReward
                  }
                }
                fragment gridRewardState on GridRewardState {
                  __typename
                  ... on GridRewardAvailable { kind }
                  ... on GridRewardUnavailable { reasons }
                  ... on GridRewardDelivering { reason }
                }
                fragment gridRewardVehicle on GridRewardVehicle {
                  kind
                  vehicleId
                  shortName
                  make
                  imgUrl
                  isPluggedIn
                  isSmartChargingEnabled
                  state { __typename ...gridRewardState }
                }
                fragment gridRewardBattery on GridRewardBattery {
                  kind
                  batteryId
                  shortName
                  make
                  imgUrl
                  isSmartModeEnabled
                  state { __typename ...gridRewardState }
                }
                fragment gridReward on GridReward {
                  homeId
                  state { __typename ...gridRewardState }
                  rewardCurrency
                  rewardCurrentMonth
                  rewardAllTime
                  flexDevices {
                    __typename
                    ... on GridRewardVehicle { __typename ...gridRewardVehicle }
                    ... on GridRewardBattery { __typename ...gridRewardBattery }
                  }
                }
                """,
            },
        }

    def _build_vehicle_state_subscribe_message(
        self, vehicle_id: str, sub_id: str
    ) -> dict[str, Any]:
        return {
            "type": "subscribe",
            "id": sub_id,
            "payload": {
                "operationName": "vehicleStateSubscription",
                "variables": {"vehicleId": vehicle_id},
                "query": """
                subscription vehicleStateSubscription($vehicleId: String!) {
                  vehicleState(vehicleId: $vehicleId) {
                    __typename
                    ...vehicleFragment
                  }
                }
                fragment setting on Setting {
                  key
                  value
                  isReadOnly
                }
                fragment vehicleFragment on Vehicle {
                  id
                  name
                  isAlive
                  chargingStatus
                  smartChargingStatus
                  hasConsumption
                  battery {
                    __typename
                    level
                  }
                  userSettings {
                    __typename
                    ...setting
                  }
                }
                """,
            },
        }

    async def set_departure_time(
        self, home_id: str, vehicle_id: str, day: str, time_str: str | None
    ) -> None:
        _LOGGER.debug(
            "Setting departure time for vehicle %s to %s on %s",
            vehicle_id,
            time_str,
            day,
        )
        token = await self.fetch_token()
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "operationName": "SetVehicleSettings",
            "variables": {
                "vehicleId": vehicle_id,
                "homeId": home_id,
                "settings": [
                    {
                        "key": f"online.vehicle.smartCharging.departureTimes.{day.lower()}",
                        "value": time_str,
                    }
                ],
            },
            "query": """
            mutation SetVehicleSettings($vehicleId: String!, $homeId: String!, $settings: [SettingsItemInput!]) {
              me {
                setVehicleSettings(id: $vehicleId, homeId: $homeId, settings: $settings) {
                  __typename
                }
              }
            }
            """,
        }
        try:
            response = await self._client.post(
                GRAPHQL_URL, headers=headers, json=payload
            )
            response.raise_for_status()
            res_json = response.json()
            if res_json.get("errors"):
                payload_offline = {
                    "operationName": "SetVehicleSettings",
                    "variables": {
                        "vehicleId": vehicle_id,
                        "homeId": home_id,
                        "settings": [
                            {
                                "key": f"offline.vehicle.departureTimes.{day.lower()}",
                                "value": time_str,
                            }
                        ],
                    },
                    "query": payload["query"],
                }
                response_offline = await self._client.post(
                    GRAPHQL_URL, headers=headers, json=payload_offline
                )
                response_offline.raise_for_status()
                if errors := response_offline.json().get("errors"):
                    raise TibberException(
                        f"Failed to set departure time for vehicle {vehicle_id}: {errors}"
                    )
            _LOGGER.debug("Successfully set departure time.")
        except httpx.HTTPStatusError as e:
            raise TibberConnectionError from e
        except TibberException:
            raise
        except Exception as e:
            raise TibberException from e

    async def set_battery_level(
        self, home_id: str, vehicle_id: str, level: int
    ) -> None:
        """Set the assumed/manual battery level for an offline vehicle.

        Confirmed (live write-then-readback test, 2026-08-16) only against an
        offline vehicle (isAlive: false). Online, API-connected vehicles
        (e.g. Tesla) don't report a usable value for battery.level either —
        confirmed live (2026-08-18) that it comes back unknown/null there —
        so this should only ever be called for vehicles confirmed offline;
        see number.py's gating.
        """
        _LOGGER.debug("Setting battery level for vehicle %s to %s", vehicle_id, level)
        token = await self.fetch_token()
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "operationName": "SetVehicleSettings",
            "variables": {
                "vehicleId": vehicle_id,
                "homeId": home_id,
                "settings": [
                    {"key": "offline.vehicle.batteryLevel", "value": str(level)}
                ],
            },
            "query": """
            mutation SetVehicleSettings($vehicleId: String!, $homeId: String!, $settings: [SettingsItemInput!]) {
              me {
                setVehicleSettings(id: $vehicleId, homeId: $homeId, settings: $settings) {
                  __typename
                }
              }
            }
            """,
        }
        try:
            response = await self._client.post(
                GRAPHQL_URL, headers=headers, json=payload
            )
            response.raise_for_status()
            if errors := response.json().get("errors"):
                raise TibberException(
                    f"Failed to set battery level for vehicle {vehicle_id}: {errors}"
                )
            _LOGGER.debug("Successfully set battery level.")
        except httpx.HTTPStatusError as e:
            raise TibberConnectionError from e
        except TibberException:
            raise
        except Exception as e:
            raise TibberException from e
