
import unittest
from unittest.mock import MagicMock

from custom_components.tibber_grid_reward.sensor import (
    GridRewardStateSensor,
    GridRewardReasonSensor,
    GridRewardCurrentMonthSensor,
    GridRewardCurrentDaySensor,
    FlexDeviceStateSensor,
    FlexDeviceConnectivitySensor,
)


class TestGridRewardSensors(unittest.TestCase):
    def setUp(self):
        self.mock_api = MagicMock()
        self.entry_id = "test_entry_id"

    def test_grid_reward_state_sensor(self):
        sensor = GridRewardStateSensor(self.mock_api, self.entry_id)
        sensor.async_write_ha_state = MagicMock()
        self.assertEqual(sensor.name, "Grid Reward State")
        self.assertEqual(sensor.unique_id, f"{self.entry_id}_grid_reward_state")
        sensor.update_data({"state": {"__typename": "GridRewardDelivering"}})
        self.assertEqual(sensor.state, "GridRewardDelivering")
        sensor.async_write_ha_state.assert_called_once()


    def test_grid_reward_reason_sensor(self):
        sensor = GridRewardReasonSensor(self.mock_api, self.entry_id)
        sensor.async_write_ha_state = MagicMock()
        self.assertEqual(sensor.name, "Grid Reward Reason")
        self.assertEqual(sensor.unique_id, f"{self.entry_id}_grid_reward_reason")
        sensor.update_data({"state": {"reasons": ["reason1", "reason2"]}})
        self.assertEqual(sensor.state, "reason1, reason2")
        sensor.async_write_ha_state.assert_called_once()

    def test_grid_reward_current_month_sensor(self):
        sensor = GridRewardCurrentMonthSensor(self.mock_api, self.entry_id)
        sensor.async_write_ha_state = MagicMock()
        self.assertEqual(sensor.name, "Grid Reward Current Month")
        self.assertEqual(sensor.unique_id, f"{self.entry_id}_grid_reward_current_month")
        sensor.update_data({"rewardCurrentMonth": 100, "rewardCurrency": "EUR"})
        self.assertEqual(sensor.state, 100)
        self.assertEqual(sensor.unit_of_measurement, "EUR")
        sensor.async_write_ha_state.assert_called_once()

    def test_grid_reward_current_day_sensor(self):
        mock_tracker = MagicMock()
        mock_tracker.daily_reward = 10.5
        sensor = GridRewardCurrentDaySensor(self.mock_api, self.entry_id, mock_tracker)
        sensor.async_write_ha_state = MagicMock()
        self.assertEqual(sensor.name, "Grid Reward Current Day")
        self.assertEqual(sensor.unique_id, f"{self.entry_id}_grid_reward_current_day")
        sensor.update_data({"rewardCurrency": "EUR"})
        self.assertEqual(sensor.state, 10.5)
        self.assertEqual(sensor.unit_of_measurement, "EUR")
        sensor.async_write_ha_state.assert_called_once()

    def test_flex_device_state_sensor(self):
        device = {"id": "vehicle1", "type": "vehicle", "name": "My Car"}
        sensor = FlexDeviceStateSensor(self.mock_api, self.entry_id, device)
        sensor.async_write_ha_state = MagicMock()
        self.assertEqual(sensor.name, "My Car State")
        self.assertEqual(sensor.unique_id, "vehicle1_state")
        sensor.update_data(
            {
                "flexDevices": [
                    {"vehicleId": "vehicle1", "state": {"__typename": "PluggedIn"}}
                ]
            }
        )
        self.assertEqual(sensor.state, "PluggedIn")
        sensor.async_write_ha_state.assert_called_once()

    def test_flex_device_connectivity_sensor(self):
        device = {"id": "vehicle1", "type": "vehicle", "name": "My Car"}
        sensor = FlexDeviceConnectivitySensor(self.mock_api, self.entry_id, device)
        sensor.async_write_ha_state = MagicMock()
        self.assertEqual(sensor.name, "My Car Connectivity")
        self.assertEqual(sensor.unique_id, "vehicle1_connectivity")
        sensor.update_data({"flexDevices": [{"vehicleId": "vehicle1", "isPluggedIn": True}]})
        self.assertEqual(sensor.state, "Plugged In")
        sensor.async_write_ha_state.assert_called_once()
