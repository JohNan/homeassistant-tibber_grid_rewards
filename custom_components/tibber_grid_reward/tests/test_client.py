
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import jwt
import httpx
import websockets

from custom_components.tibber_grid_reward.client import TibberAPI, TibberAuthError, TibberException, TibberConnectionError

class TestTibberAPI(unittest.TestCase):
    def setUp(self):
        self.mock_client = AsyncMock(spec=httpx.AsyncClient)
        self.api = TibberAPI("test_user", "test_pass", self.mock_client)

    @patch("time.time")
    def test_fetch_token_success(self, mock_time):
        mock_time.return_value = 1678886400
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "token": jwt.encode({"exp": 1678886400 + 3600}, "secret")
        }
        self.mock_client.post.return_value = mock_response

        async def run_test():
            token = await self.api.fetch_token()
            self.assertIsNotNone(token)
            self.assertEqual(token, self.api._cached_token)
            self.mock_client.post.assert_called_once()

        asyncio.run(run_test())

    @patch("time.time")
    def test_fetch_token_cached(self, mock_time):
        mock_time.return_value = 1678886400
        self.api._cached_token = "test_token"
        self.api._cached_exp = 1678886400 + 3600

        async def run_test():
            token = await self.api.fetch_token()
            self.assertEqual(token, "test_token")
            self.mock_client.post.assert_not_called()

        asyncio.run(run_test())

    def test_fetch_token_auth_error(self):
        self.mock_client.post.side_effect = httpx.HTTPStatusError(
            "Auth error", request=MagicMock(), response=MagicMock()
        )

        async def run_test():
            with self.assertRaises(TibberAuthError):
                await self.api.fetch_token()

        asyncio.run(run_test())

    def test_fetch_token_generic_error(self):
        self.mock_client.post.side_effect = Exception("Generic error")

        async def run_test():
            with self.assertRaises(TibberException):
                await self.api.fetch_token()

        asyncio.run(run_test())

    @patch("custom_components.tibber_grid_reward.client.TibberAPI.fetch_token", new_callable=AsyncMock)
    def test_get_homes_success(self, mock_fetch_token):
        mock_fetch_token.return_value = "test_token"
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {"me": {"homes": [{"id": "home1"}, {"id": "home2"}]}}
        }
        self.mock_client.post.return_value = mock_response

        async def run_test():
            homes = await self.api.get_homes()
            self.assertEqual(len(homes), 2)
            self.assertEqual(homes[0]["id"], "home1")
            self.mock_client.post.assert_called_once()

        asyncio.run(run_test())

    @patch("custom_components.tibber_grid_reward.client.TibberAPI.fetch_token", new_callable=AsyncMock)
    def test_get_homes_connection_error(self, mock_fetch_token):
        mock_fetch_token.return_value = "test_token"
        self.mock_client.post.side_effect = httpx.HTTPStatusError(
            "Connection error", request=MagicMock(), response=MagicMock()
        )

        async def run_test():
            with self.assertRaises(TibberConnectionError):
                await self.api.get_homes()

        asyncio.run(run_test())

    @patch("websockets.connect")
    @patch("custom_components.tibber_grid_reward.client.TibberAPI.fetch_token", new_callable=AsyncMock)
    def test_validate_grid_reward_success(self, mock_fetch_token, mock_ws_connect):
        async def run_test():
            mock_fetch_token.return_value = "test_token"
            mock_websocket = AsyncMock()
            mock_ws_connect.return_value.__aenter__.return_value = mock_websocket
            
            async def mock_recv():
                return '{"type": "connection_ack"}'
            
            async def mock_recv2():
                return '{"type": "next", "payload": {"data": {"gridRewardStatus": {"status": "ok"}}}}'

            mock_websocket.recv.side_effect = [await mock_recv(), await mock_recv2()]

            result = await self.api.validate_grid_reward("home1")
            self.assertEqual(result, {"status": "ok"})
            mock_websocket.send.assert_any_call('{"type": "connection_init"}')
        
        asyncio.run(run_test())

    @patch("websockets.connect")
    @patch("custom_components.tibber_grid_reward.client.TibberAPI.fetch_token", new_callable=AsyncMock)
    def test_validate_grid_reward_connection_error(self, mock_fetch_token, mock_ws_connect):
        async def run_test():
            mock_fetch_token.return_value = "test_token"
            mock_ws_connect.side_effect = websockets.exceptions.WebSocketException("Connection failed")

            with self.assertRaises(TibberConnectionError):
                await self.api.validate_grid_reward("home1")
        
        asyncio.run(run_test())

    @patch("custom_components.tibber_grid_reward.client.TibberAPI.fetch_token", new_callable=AsyncMock)
    def test_set_departure_time_success(self, mock_fetch_token):
        async def run_test():
            mock_fetch_token.return_value = "test_token"
            mock_response = MagicMock()
            mock_response.raise_for_status.return_value = None
            self.mock_client.post.return_value = mock_response

            await self.api.set_departure_time("home1", "vehicle1", "monday", "08:00")
            self.mock_client.post.assert_called_once()

        asyncio.run(run_test())

    @patch("custom_components.tibber_grid_reward.client.TibberAPI.fetch_token", new_callable=AsyncMock)
    def test_set_departure_time_connection_error(self, mock_fetch_token):
        async def run_test():
            mock_fetch_token.return_value = "test_token"
            self.mock_client.post.side_effect = httpx.HTTPStatusError(
                "Connection error", request=MagicMock(), response=MagicMock()
            )

            with self.assertRaises(TibberConnectionError):
                await self.api.set_departure_time("home1", "vehicle1", "monday", "08:00")

        asyncio.run(run_test())

if __name__ == "__main__":
    unittest.main()

