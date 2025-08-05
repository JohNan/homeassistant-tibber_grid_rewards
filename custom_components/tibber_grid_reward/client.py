import asyncio
import logging
import time
import jwt
import websockets
import httpx
import json
import uuid
from typing import Callable, Any, List, Dict

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

class TibberAPI:
    def __init__(self, username: str, password: str, client: httpx.AsyncClient):
        self.username: str = username
        self.password: str = password
        self._client: httpx.AsyncClient = client
        self._cached_token: str | None = None
        self._cached_exp: float = 0
        self._ws_reconnect: bool = True
        self._websocket: websockets.client.WebSocketClientProtocol | None = None
        self._sub_callback: Callable[[Dict[str, Any]], None] | None = None
        self._vehicle_callbacks: Dict[str, Callable[[Dict[str, Any]], None]] = {}
        self.home_id: str | None = None

    async def close_websocket(self) -> None:
        self._ws_reconnect = False
        if self._websocket and not self._websocket.closed:
            await self._websocket.close()

    async def fetch_token(self) -> str:
        now = time.time()
        if self._cached_token and (self._cached_exp - now > 30):
            return self._cached_token

        _LOGGER.debug("Fetching new Tibber token.")
        try:
            response = await self._client.post(
                AUTH_URL,
                json={"email": self.username, "password": self.password},
                timeout=10
            )
            response.raise_for_status()
            data: Dict[str, Any] = response.json()
            token: str = data.get("token")
            decoded: Dict[str, Any] = jwt.decode(token, options={"verify_signature": False})
            self._cached_exp = decoded.get("exp", 0)
            self._cached_token = token
            _LOGGER.debug("Successfully fetched new Tibber token.")
            return token
        except httpx.HTTPStatusError as e:
            raise TibberAuthError from e
        except Exception as e:
            raise TibberException from e

    async def get_homes(self) -> List[Dict[str, Any]]:
        _LOGGER.debug("Fetching Tibber homes.")
        token = await self.fetch_token()
        headers = {"Authorization": f"Bearer {token}"}
        query = "{ me { homes { id title } } }"
        try:
            response = await self._client.post(GRAPHQL_URL, headers=headers, json={"query": query})
            response.raise_for_status()
            _LOGGER.debug("Successfully fetched Tibber homes.")
            return response.json().get("data", {}).get("me", {}).get("homes", [])
        except httpx.HTTPStatusError as e:
            raise TibberConnectionError from e
        except Exception as e:
            raise TibberException from e

    async def validate_grid_reward(self, home_id: str) -> Dict[str, Any] | None:
        _LOGGER.debug("Validating grid reward for home: %s", home_id)
        token = await self.fetch_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        try:
            async with websockets.connect(
                GRAPHQL_WS_URL,
                additional_headers=headers,
                subprotocols=["graphql-transport-ws"],
            ) as websocket:
                await websocket.send(json.dumps({"type": "connection_init"}))
                msg = await asyncio.wait_for(websocket.recv(), timeout=10)
                if json.loads(msg).get("type") != "connection_ack":
                    raise TibberConnectionError("Connection ACK not received.")

                subscribe_msg = self._build_grid_reward_subscribe_message(home_id, "1")
                await websocket.send(json.dumps(subscribe_msg))
                msg = await asyncio.wait_for(websocket.recv(), timeout=10)
                data: Dict[str, Any] = json.loads(msg)

                if data.get("type") == "next":
                    _LOGGER.debug("Successfully validated grid reward.")
                    return data.get("payload", {}).get("data", {}).get("gridRewardStatus")
                return None
        except (asyncio.TimeoutError, websockets.exceptions.WebSocketException) as e:
            raise TibberConnectionError from e
        except Exception as e:
            raise TibberException from e

    def register_grid_reward_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._sub_callback = callback

    def register_vehicle_callback(self, vehicle_id: str, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._vehicle_callbacks[vehicle_id] = callback

    async def subscribe_grid_reward(self, home_id: str) -> None:
        self.home_id = home_id
        self._ws_reconnect = True
        _LOGGER.info("Starting Tibber grid reward websocket subscription.")
        try:
            while self._ws_reconnect:
                try:
                    token = await self.fetch_token()
                    headers = {"Authorization": f"Bearer {token}"}
                    async with websockets.connect(
                        GRAPHQL_WS_URL,
                        additional_headers=headers,
                        subprotocols=["graphql-transport-ws"],
                    ) as websocket:
                        self._websocket = websocket
                        await websocket.send(json.dumps({"type": "connection_init"}))
                        
                        current_sub_id: str | None = None
                        while True:
                            msg = await websocket.recv()
                            data: Dict[str, Any] = json.loads(msg)

                            if data.get("type") == "connection_ack":
                                _LOGGER.debug("Websocket connection acknowledged.")
                                current_sub_id = str(uuid.uuid4())
                                subscribe_msg = self._build_grid_reward_subscribe_message(self.home_id, current_sub_id)
                                await websocket.send(json.dumps(subscribe_msg))
                            elif data.get("type") == "next":
                                reward_data = data.get("payload", {}).get("data", {}).get("gridRewardStatus")
                                _LOGGER.debug("Grid reward data received: %s", data)
                                if reward_data and self._sub_callback:
                                    self._sub_callback(reward_data)
                            elif data.get("type") == "complete" and data.get("id") == current_sub_id:
                                current_sub_id = str(uuid.uuid4())
                                _LOGGER.debug("Subscription complete, re-subscribing.")
                                subscribe_msg = self._build_grid_reward_subscribe_message(self.home_id, current_sub_id)
                                await websocket.send(json.dumps(subscribe_msg))
                            #else:
                            #    _LOGGER.debug("Grid reward data received: %s", data)
                except (websockets.exceptions.ConnectionClosedError, websockets.exceptions.ConnectionClosedOK):
                    if not self._ws_reconnect:
                        break
                    _LOGGER.warning("Websocket connection closed, reconnecting in 5 seconds.")
                except Exception:
                    _LOGGER.exception("Error in websocket subscription, reconnecting in 5 seconds.")
                
                if self._ws_reconnect:
                    await asyncio.sleep(5)
        except asyncio.CancelledError:
            _LOGGER.info("Tibber websocket subscription task cancelled.")
            raise

    async def subscribe_vehicle_state(self, vehicle_id: str) -> None:
        self._ws_reconnect = True
        _LOGGER.info("Starting Tibber vehicle state websocket subscription for %s.", vehicle_id)
        try:
            while self._ws_reconnect:
                try:
                    token = await self.fetch_token()
                    headers = {"Authorization": f"Bearer {token}"}
                    async with websockets.connect(
                        GRAPHQL_WS_URL,
                        additional_headers=headers,
                        subprotocols=["graphql-transport-ws"],
                    ) as websocket:
                        self._websocket = websocket
                        await websocket.send(json.dumps({"type": "connection_init"}))
                        
                        current_sub_id: str | None = None
                        while True:
                            msg = await websocket.recv()
                            data: Dict[str, Any] = json.loads(msg)

                            if data.get("type") == "connection_ack":
                                _LOGGER.debug("Websocket connection acknowledged.")
                                current_sub_id = str(uuid.uuid4())
                                subscribe_msg = self._build_vehicle_state_subscribe_message(vehicle_id, current_sub_id)
                                await websocket.send(json.dumps(subscribe_msg))
                            elif data.get("type") == "next":
                                _LOGGER.debug("Vehicle state data received: %s", data)
                                vehicle_data = data.get("payload", {}).get("data", {}).get("vehicleState")
                                if vehicle_data and self._vehicle_callbacks.get(vehicle_id):
                                    self._vehicle_callbacks[vehicle_id](vehicle_data)
                            elif data.get("type") == "complete" and data.get("id") == current_sub_id:
                                _LOGGER.debug("Subscription complete, re-subscribing.")
                                current_sub_id = str(uuid.uuid4())
                                subscribe_msg = self._build_vehicle_state_subscribe_message(vehicle_id, current_sub_id)
                                await websocket.send(json.dumps(subscribe_msg))
                except (websockets.exceptions.ConnectionClosedError, websockets.exceptions.ConnectionClosedOK):
                    if not self._ws_reconnect:
                        break
                    _LOGGER.warning("Websocket connection closed, reconnecting in 5 seconds.")
                except Exception:
                    _LOGGER.exception("Error in websocket subscription, reconnecting in 5 seconds.")
                
                if self._ws_reconnect:
                    await asyncio.sleep(5)
        except asyncio.CancelledError:
            _LOGGER.info("Tibber websocket subscription task cancelled.")
            raise

    def _build_grid_reward_subscribe_message(self, home_id: str, sub_id: str) -> Dict[str, Any]:
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
                """
            }
        }

    def _build_vehicle_state_subscribe_message(self, vehicle_id: str, sub_id: str) -> Dict[str, Any]:
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
                  userSettings {
                    __typename
                    ...setting
                  }
                }
                """
            }
        }
    
    async def set_departure_time(self, home_id: str, vehicle_id: str, day: str, time_str: str | None) -> None:
        _LOGGER.debug("Setting departure time for vehicle %s to %s on %s", vehicle_id, time_str, day)
        token = await self.fetch_token()
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "operationName": "SetVehicleSettings",
            "variables": {
                "vehicleId": vehicle_id,
                "homeId": home_id,
                "settings": [{
                    "key": f"online.vehicle.smartCharging.departureTimes.{day.lower()}",
                    "value": time_str
                }]
            },
            "query": """
            mutation SetVehicleSettings($vehicleId: String!, $homeId: String!, $settings: [SettingsItemInput!]) {
              me {
                setVehicleSettings(id: $vehicleId, homeId: $homeId, settings: $settings) {
                  __typename
                }
              }
            }
            """
        }
        try:
            response = await self._client.post(GRAPHQL_URL, headers=headers, json=payload)
            response.raise_for_status()
            _LOGGER.debug("Successfully set departure time.")
        except httpx.HTTPStatusError as e:
            raise TibberConnectionError from e
        except Exception as e:
            raise TibberException from e
