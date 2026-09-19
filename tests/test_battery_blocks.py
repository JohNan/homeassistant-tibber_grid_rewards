"""Tests for modular GraphQL query blocks and GraphQLQueryComposer."""
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from custom_components.tibber_grid_reward.battery_blocks import (
    BatteryDataBlock,
    BatteryQueryComposer,
    BatterySavingsBlock,
    GraphQLQueryBlock,
    GraphQLQueryComposer,
)
from custom_components.tibber_grid_reward.client import TibberAPI
from custom_components.tibber_grid_reward.coordinator import (
    TibberBatteryData,
    TibberBatteryDataCoordinator,
)


class CustomTestBlock(BatteryDataBlock):
    """Custom block implementation for testing modularity on me.home."""

    name = "custom_test"

    def get_variable_definitions(self) -> dict[str, str]:
        return {"$customParam": "Boolean!"}

    def get_variables(
        self, now: datetime, home_id: str, device_id: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        return {"customParam": True}

    def get_query_fragment(self) -> str:
        return """customTelemetry(enabled: $customParam) {
  status
}"""

    def parse_response(self, home_data: dict[str, Any]) -> Any:
        return (home_data.get("customTelemetry") or {}).get("status")


class CustomRootBlock(GraphQLQueryBlock):
    """Custom query block operating at me root for generic queries."""

    name = "user_profile"
    root_field = "me"

    def get_query_fragment(self) -> str:
        return """name
email"""

    def parse_response(self, root_data: dict[str, Any]) -> Any:
        return {
            "name": root_data.get("name"),
            "email": root_data.get("email"),
        }


def test_battery_query_composer_defaults():
    """Test BatteryQueryComposer default blocks and query generation."""
    composer = BatteryQueryComposer(operation_name="GetBatteryDetails")
    assert len(composer.blocks) == 3
    assert [b.name for b in composer.blocks] == ["savings", "activity", "planned"]

    now = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
    variables = composer.build_variables(now, "home_123", "bat_456")

    assert variables["homeId"] == "home_123"
    assert variables["deviceId"] == "bat_456"
    assert variables["activityTo"] == "2026-09-19T13:00:00Z"
    assert variables["activityFrom"] == "2026-09-19T06:00:00Z"
    assert variables["timelineFrom"] == "2026-09-19T12:00:00Z"
    assert variables["timelineTo"] == "2026-09-20T23:59:59Z"
    assert variables["resolution"] == "QUARTER_HOURLY"

    query = composer.build_query()
    assert "query GetBatteryDetails(" in query
    assert "$homeId: String!" in query
    assert "$deviceId: String!" in query
    assert "$activityFrom: DateTime!" in query
    assert "$timelineFrom: DateTime!" in query
    assert "battery(id: $deviceId)" in query
    assert "batteryActivityHistory(id: $deviceId, from: $activityFrom, to: $activityTo)" in query
    assert "batteryTimeline(" in query


def test_battery_query_composer_add_custom_block():
    """Test adding custom block to composer."""
    composer = BatteryQueryComposer()
    composer.add_block(CustomTestBlock())

    assert len(composer.blocks) == 4
    now = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
    variables = composer.build_variables(now, "home_123", "bat_456")
    assert variables["customParam"] is True

    query = composer.build_query()
    assert "$customParam: Boolean!" in query
    assert "customTelemetry(enabled: $customParam)" in query

    raw_response = {
        "data": {
            "me": {
                "home": {
                    "battery": {
                        "aggregatedHistory": {
                            "periods": [
                                {
                                    "key": "TODAY",
                                    "batteryValueItems": [{"value": 10.5, "unit": "NOK", "kind": "TOTAL"}],
                                }
                            ]
                        }
                    },
                    "batteryActivityHistory": {"items": [{"from": "2026-09-19T10:00:00Z"}]},
                    "batteryTimeline": {
                        "energyFlow": {"items": [{"time": "2026-09-19T12:00:00Z", "charged": 1000}]},
                        "stateOfCharge": {"items": [{"time": "2026-09-19T12:00:00Z", "stateOfCharge": 55.0}]},
                    },
                    "customTelemetry": {"status": "ACTIVE"},
                }
            }
        }
    }

    parsed = composer.parse_response(raw_response)
    assert parsed["savings"]["TODAY"]["value"] == 10.5
    assert len(parsed["activity"]) == 1
    assert len(parsed["planned"]) == 1
    assert parsed["custom_test"] == "ACTIVE"


def test_generic_graphql_query_composer_me_root():
    """Test GraphQLQueryComposer with generic me root."""
    composer = GraphQLQueryComposer(
        blocks=[CustomRootBlock()],
        operation_name="GetUserProfile",
        root_field="me",
    )

    query = composer.build_query()
    assert "query GetUserProfile {" in query
    assert "me {" in query
    assert "name" in query
    assert "email" in query

    raw_response = {
        "data": {
            "me": {
                "name": "Jane Doe",
                "email": "jane@example.com",
            }
        }
    }

    parsed = composer.parse_response(raw_response)
    assert parsed["user_profile"] == {"name": "Jane Doe", "email": "jane@example.com"}


def test_tibber_battery_data_access():
    """Test TibberBatteryData attribute and item access for extra blocks."""
    data = TibberBatteryData(
        savings={"TODAY": {"value": 15}},
        activity=[{"from": "now"}],
        planned=[],
        extra={"custom_test": "ONLINE", "foo": 42},
    )

    # Standard attributes
    assert data.savings["TODAY"]["value"] == 15
    assert len(data.activity) == 1
    assert data.get("savings") == {"TODAY": {"value": 15}}
    assert data["savings"] == {"TODAY": {"value": 15}}

    # Extra custom blocks
    assert data.get("custom_test") == "ONLINE"
    assert data["custom_test"] == "ONLINE"
    assert data["foo"] == 42
    assert data.get("nonexistent", "fallback") == "fallback"


async def test_coordinator_with_custom_block(hass):
    """Test TibberBatteryDataCoordinator populates extra block in data."""
    api = MagicMock(spec=TibberAPI)
    composer = BatteryQueryComposer([
        BatterySavingsBlock(),
        CustomTestBlock(),
    ])

    api.get_battery_details = AsyncMock(
        return_value={
            "savings": {"TODAY": {"value": 20.0}},
            "activity": [],
            "planned": [],
            "custom_test": "TEST_DATA_OK",
        }
    )

    coordinator = TibberBatteryDataCoordinator(
        hass=hass,
        api=api,
        home_id="home_1",
        battery_id="bat_1",
        composer=composer,
    )

    await coordinator.async_refresh()

    assert coordinator.data.savings["TODAY"]["value"] == 20.0
    assert coordinator.data.get("custom_test") == "TEST_DATA_OK"
    assert coordinator.data["custom_test"] == "TEST_DATA_OK"
    assert coordinator.data.extra["custom_test"] == "TEST_DATA_OK"
