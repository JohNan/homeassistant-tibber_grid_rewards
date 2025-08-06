# Tibber Grid Reward

This is a custom integration for Home Assistant that allows you to monitor and interact with the Tibber Grid Reward program.

## Features

- **Grid Reward Sensors**: Provides sensors for the current state of the grid reward, the reason for the current state, and the earnings for the current day and month.
- **Live Session Reward**: A sensor that shows the live, accumulating reward amount during an active grid reward session.
- **Flexible Device Sensors**: Provides sensors for the state and connectivity of your flexible devices (e.g., electric vehicles).
- **Departure Time Control**: Allows you to set the departure time for your electric vehicles directly from Home Assistant.

## Installation

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
