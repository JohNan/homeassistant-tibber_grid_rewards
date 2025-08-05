
import unittest
from unittest.mock import MagicMock, patch

from custom_components.tibber_grid_reward.binary_sensor import GridRewardActiveSensor
from custom_components.tibber_grid_reward.const import DOMAIN


class TestGridRewardActiveSensor(unittest.TestCase):
    def setUp(self):
        self.mock_api = MagicMock()
        self.sensor = GridRewardActiveSensor(self.mock_api, "test_entry_id")
        self.sensor.async_write_ha_state = MagicMock()

    def test_initial_state(self):
        self.assertFalse(self.sensor.is_on)
        self.assertEqual(self.sensor.name, "Grid Reward Active")
        self.assertEqual(self.sensor.unique_id, "test_entry_id_grid_reward_active")

    def test_device_info(self):
        self.assertEqual(
            self.sensor.device_info,
            {
                "identifiers": {(DOMAIN, "test_entry_id")},
                "name": "Tibber Grid Reward",
                "manufacturer": "Tibber",
            },
        )

    def test_update_data(self):
        self.sensor.update_data({"state": {"__typename": "GridRewardDelivering"}})
        self.assertTrue(self.sensor.is_on)
        self.sensor.async_write_ha_state.assert_called_once()

        self.sensor.update_data({"state": {"__typename": "GridRewardAvailable"}})
        self.assertFalse(self.sensor.is_on)
        self.assertEqual(self.sensor.async_write_ha_state.call_count, 2)

if __name__ == "__main__":
    unittest.main()
