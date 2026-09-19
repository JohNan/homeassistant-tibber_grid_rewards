# Tibber Grid Reward

This is a custom integration for Home Assistant that allows you to monitor and interact with the Tibber Grid Reward program.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=JohNan&repository=homeassistant-tibber_grid_rewards&category=integration)

## Features

- **Grid Reward Sensors**: Provides sensors for the current state of the grid reward, the reason for the current state, and the earnings for the current day and month.
- **Live Session Reward**: A sensor that shows the live, accumulating reward amount during an active grid reward session.
- **Battery Sensors (Consolidated Coordinator)**: For home batteries, coordinates all telemetry within a single consolidated GraphQL query via Home Assistant's `DataUpdateCoordinator`:
  - **Savings Sensors**: Total savings for today, this week, and this month (the figure the Tibber app displays as "Your total savings" on the battery screen).
  - **Activity Reason Sensor**: Explains current battery behavior and state transitions, distinguishing grid rewards (`HomeBatteryChargingForGridRewards`, `HomeBatteryDischargingForGridRewards`) from price arbitrage, solar charging, fuse protection, etc.
  - **Planned Activity Sensor**: Timestamp of the next scheduled charge/discharge event, with attributes containing the full quarter-hourly power flow and state-of-charge schedule through tomorrow.
- **Modular Query Composer**: Extensible query block engine (`BatteryDataBlock` and `BatteryQueryComposer`) allowing custom telemetry fragments and response parsers to be added without modifying core polling logic.
- **Flexible Device Sensors**: Provides sensors for the state and connectivity of your flexible devices (e.g., electric vehicles).
- **Departure Time Control**: Allows you to set the departure time for your electric vehicles directly from Home Assistant.

## Battery Telemetry Architecture

Battery telemetry is retrieved every 5 minutes (and immediately upon WebSocket state changes) using a single consolidated GraphQL request managed by `TibberBatteryDataCoordinator`.

### Modular Query Blocks (`BatteryDataBlock`)

The query is composed dynamically using modular blocks subclassing `BatteryDataBlock`:
- `BatterySavingsBlock`: Fetches `aggregatedHistory` for `TODAY`, `WEEK`, and `MONTH`.
- `BatteryActivityBlock`: Fetches `batteryActivityHistory` intervals and reason typenames.
- `BatteryPlannedBlock`: Fetches `batteryTimeline` energy flow and quarter-hourly state-of-charge.

#### Extending with Custom Telemetry

Custom telemetry blocks can be defined and plugged into `BatteryQueryComposer`:

```python
from custom_components.tibber_grid_reward.battery_blocks import BatteryDataBlock

class CustomTelemetryBlock(BatteryDataBlock):
    name = "custom_telemetry"

    def get_variable_definitions(self) -> dict[str, str]:
        return {"$limit": "Int!"}

    def get_variables(self, now, home_id, battery_id) -> dict[str, Any]:
        return {"limit": 10}

    def get_query_fragment(self) -> str:
        return """customTelemetry(id: $deviceId, limit: $limit) {
  status
  metrics {
    timestamp
    value
  }
}"""

    def parse_response(self, home_data: dict[str, Any]) -> Any:
        return (home_data.get("customTelemetry") or {}).get("metrics", [])
```

The parsed data is automatically made available in `coordinator.data`:
```python
metrics = coordinator.data["custom_telemetry"]
# or
metrics = coordinator.data.get("custom_telemetry")
```

## Installation

### HACS (Recommended)

1. Add this repository as a custom repository in HACS.
2. Search for "Tibber Grid Reward" in HACS and install it.
3. Restart Home Assistant.
4. Add the "Tibber Grid Reward" integration from the Home Assistant UI.

### Manual Installation

1. Copy the `tibber_grid_reward` directory to your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Add the "Tibber Grid Reward" integration from the Home Assistant UI.

## Configuration

The integration is configured through the Home Assistant UI. You will need to provide your Tibber username and password.

## Services

### `tibber_grid_reward.set_departure_time`

Sets the departure time for a vehicle.

| Service Data | Description                                 |
|--------------|---------------------------------------------|
| `device_id`  | The device ID of the vehicle.               |
| `day`        | The day of the week (e.g., "monday").       |
| `time`       | The departure time in "HH:MM" format.       |

## Disclaimer

This integration is not developed, endorsed, or supported by Tibber. It is an unofficial, community-developed project.