
import unittest
from unittest.mock import MagicMock, AsyncMock
import datetime

from custom_components.tibber_grid_reward.time import DepartureTimeEntity
from custom_components.tibber_grid_reward.const import DOMAIN


class TestDepartureTimeEntity(unittest.TestCase):
    def setUp(self):
        self.mock_api = MagicMock()
        self.mock_api.set_departure_time = AsyncMock()
        self.entry_id = "test_entry_id"
        self.device = {"id": "vehicle1", "type": "vehicle", "name": "My Car"}
        self.sensor = DepartureTimeEntity(self.mock_api, self.entry_id, self.device, 0)
        self.sensor.async_write_ha_state = MagicMock()

    def test_initial_state(self):
        self.assertEqual(self.sensor.name, "My Car Departure Time Monday")
        self.assertEqual(self.sensor.unique_id, "vehicle1_departure_time_monday")
        self.assertIsNone(self.sensor.native_value)

    def test_device_info(self):
        self.assertEqual(
            self.sensor.device_info,
            {
                "identifiers": {(DOMAIN, "vehicle1")},
            },
        )

    def test_update_data(self):
        self.sensor.update_data(
            {
                "userSettings": [
                    {
                        "key": "online.vehicle.smartCharging.departureTimes.monday",
                        "value": "08:00",
                    }
                ]
            }
        )
        self.assertEqual(self.sensor.native_value, datetime.time(8, 0))
        self.sensor.async_write_ha_state.assert_called_once()

    def test_async_set_value(self):
        async def run_test():
            await self.sensor.async_set_value(datetime.time(9, 30))
            self.mock_api.set_departure_time.assert_called_once_with(
                home_id=self.mock_api.home_id,
                vehicle_id="vehicle1",
                day="monday",
                time_str="09:30",
            )
            self.assertEqual(self.sensor.native_value, datetime.time(9, 30))
            self.sensor.async_write_ha_state.assert_called_once()
        
        import asyncio
        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
