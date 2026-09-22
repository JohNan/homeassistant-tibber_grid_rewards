"""Tests for modular GraphQL query blocks and GraphQLQueryComposer."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from custom_components.tibber_grid_reward.battery_blocks import (
    BatteryDataBlock,
    BatteryPlannedBlock,
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

    now = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
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
    assert (
        "batteryActivityHistory(id: $deviceId, from: $activityFrom, to: $activityTo)"
        in query
    )
    assert "batteryTimeline(" in query


def test_battery_query_composer_add_custom_block():
    """Test adding custom block to composer."""
    composer = BatteryQueryComposer()
    composer.add_block(CustomTestBlock())

    assert len(composer.blocks) == 4
    now = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
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
                                    "batteryValueItems": [
                                        {"value": 10.5, "unit": "NOK", "kind": "TOTAL"}
                                    ],
                                }
                            ]
                        }
                    },
                    "batteryActivityHistory": {
                        "items": [{"from": "2026-09-19T10:00:00Z"}]
                    },
                    "batteryTimeline": {
                        "energyFlow": {
                            "items": [{"time": "2026-09-19T12:00:00Z", "charged": 1000}]
                        },
                        "stateOfCharge": {
                            "items": [
                                {"time": "2026-09-19T12:00:00Z", "stateOfCharge": 55.0}
                            ]
                        },
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
    composer = BatteryQueryComposer(
        [
            BatterySavingsBlock(),
            CustomTestBlock(),
        ]
    )

    api.execute_query_blocks = AsyncMock(
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


def test_tibber_block_data_uniformity():
    """Verify pre-made battery blocks and custom blocks are treated identically."""
    raw = {
        "savings": {"TODAY": {"value": 50}},
        "activity": [{"from": "now"}],
        "planned": [{"kind": "FORECAST"}],
        "solar_stats": {"generated_kwh": 12.5},
        "grid_metrics": {"voltage": 230},
    }
    block_data = TibberBatteryData(raw)

    # All blocks are accessible via get()
    assert block_data.get("savings") == {"TODAY": {"value": 50}}
    assert block_data.get("solar_stats") == {"generated_kwh": 12.5}
    assert block_data.get("grid_metrics") == {"voltage": 230}
    assert block_data.get("missing", 999) == 999

    # All blocks are accessible via dict subscription
    assert block_data["savings"] == {"TODAY": {"value": 50}}
    assert block_data["solar_stats"] == {"generated_kwh": 12.5}
    assert block_data["grid_metrics"] == {"voltage": 230}

    # All blocks are accessible via attribute access
    assert block_data.savings == {"TODAY": {"value": 50}}
    assert block_data.solar_stats == {"generated_kwh": 12.5}
    assert block_data.grid_metrics == {"voltage": 230}

    # Membership and iteration
    assert "savings" in block_data
    assert "solar_stats" in block_data
    assert "nonexistent" not in block_data
    assert set(block_data) == {
        "savings",
        "activity",
        "planned",
        "solar_stats",
        "grid_metrics",
    }
    assert len(block_data) == 5
    assert bool(block_data) is True

    # Equality with another container or dict
    assert block_data == TibberBatteryData(raw)
    assert block_data == raw

    # Empty container
    empty = TibberBatteryData()
    assert bool(empty) is False
    assert len(empty) == 0
    assert empty.savings == {}
    assert empty.activity == []
    assert empty.planned == []


async def test_coordinator_execute_query_blocks_path(hass):
    """Test TibberQueryDataCoordinator executing via execute_query_blocks on api."""
    mock_api = MagicMock()
    mock_api.execute_query_blocks = AsyncMock(
        return_value={
            "savings": {"TODAY": {"value": 35.0}},
            "activity": [],
            "planned": [],
            "custom_block": {"status": "ACTIVE"},
        }
    )

    coordinator = TibberBatteryDataCoordinator(
        hass=hass,
        api=mock_api,
        home_id="home_1",
        battery_id="bat_1",
    )

    await coordinator.async_refresh()

    mock_api.execute_query_blocks.assert_awaited_once_with(
        coordinator.composer,
        "home_1",
        device_id="bat_1",
    )
    assert coordinator.data["savings"]["TODAY"]["value"] == 35.0
    assert coordinator.data["custom_block"] == {"status": "ACTIVE"}
    assert coordinator.data.custom_block == {"status": "ACTIVE"}


def test_generic_query_block_factory():
    """Test creating query blocks via GenericQueryBlock and create_query_block."""
    from custom_components.tibber_grid_reward.query_blocks import (
        GenericQueryBlock,
        create_query_block,
    )

    block = create_query_block(
        name="solar_inverter",
        query_fragment="solar { currentPower totalEnergy }",
        parse_fn=lambda d: d.get("solar", {}).get("currentPower"),
        variable_definitions={"$solarFilter": "Boolean!"},
        variables_fn=lambda **kwargs: {"solarFilter": True},
    )

    assert isinstance(block, GenericQueryBlock)
    assert block.name == "solar_inverter"
    assert block.get_query_fragment() == "solar { currentPower totalEnergy }"
    assert block.get_variable_definitions() == {"$solarFilter": "Boolean!"}
    assert block.get_variables(datetime.now(UTC), "home1") == {"solarFilter": True}
    assert block.parse_response({"solar": {"currentPower": 3200}}) == 3200


def test_query_block_registry():
    """Test registry operations: register, retrieve, list, and error handling."""
    import pytest

    from custom_components.tibber_grid_reward.query_blocks import (
        GLOBAL_QUERY_BLOCK_REGISTRY,
        QueryBlockRegistry,
        create_query_block,
    )

    registry = QueryBlockRegistry()
    test_block = create_query_block("test_sensor", "sensor { val }")

    # Register instance
    registry.register(test_block)
    assert "test_sensor" in registry
    assert registry.get("test_sensor") is test_block
    assert registry.get_or_create(test_block) is test_block
    assert registry.get_or_create("test_sensor") is test_block
    assert "test_sensor" in registry.list_blocks()

    # Pre-made battery blocks are in global registry
    assert "savings" in GLOBAL_QUERY_BLOCK_REGISTRY
    assert "activity" in GLOBAL_QUERY_BLOCK_REGISTRY
    assert "planned" in GLOBAL_QUERY_BLOCK_REGISTRY

    # Missing block error
    with pytest.raises(KeyError, match="not registered"):
        registry.get("nonexistent_block")

    # Anonymous block error
    with pytest.raises(ValueError, match="must specify a name"):
        registry.register(object())


def test_composer_with_string_block_names():
    """Test composing queries using string block names resolved from registry."""
    from custom_components.tibber_grid_reward.query_blocks import (
        create_query_composer,
    )

    composer = create_query_composer(blocks=["savings", "activity"])
    assert len(composer.blocks) == 2
    assert [b.name for b in composer.blocks] == ["savings", "activity"]

    query = composer.build_query()
    assert "battery(id: $deviceId)" in query
    assert "batteryActivityHistory" in query


async def test_coordinator_with_blocks_sequence(hass):
    """Test initializing coordinator directly with a sequence of block names."""
    mock_api = MagicMock()
    mock_api.execute_query_blocks = AsyncMock(
        return_value={
            "savings": {"TODAY": {"value": 10.0}},
            "activity": [],
        }
    )

    coordinator = TibberBatteryDataCoordinator(
        hass=hass,
        api=mock_api,
        home_id="home_1",
        battery_id="bat_1",
        blocks=["savings", "activity"],
    )

    await coordinator.async_refresh()
    assert len(coordinator.composer.blocks) == 2
    assert coordinator.data["savings"]["TODAY"]["value"] == 10.0


def test_query_composer_null_data_handling():
    """Test parse_response handles null or missing data without raising TypeError."""
    composer = BatteryQueryComposer()
    res_null = composer.parse_response(
        {"data": None, "errors": [{"message": "Unauthorized"}]}
    )
    assert res_null["savings"] == {}
    assert res_null["activity"] == []
    assert res_null["planned"] == []

    res_empty_str = composer.parse_response("not-a-dict")  # type: ignore[arg-type]
    assert res_empty_str["savings"] == {}


def test_query_composer_variable_normalization():
    """Test build_query prepends $ to variable definitions and build_variables strips $ from keys."""

    class CustomVarBlock(GraphQLQueryBlock):
        name = "custom_var"

        def get_variable_definitions(self):
            return {"unprefixed": "String!", "$prefixed": "Int!"}

        def get_variables(self, now, home_id, device_id=None, **kwargs):
            return {"$prefixed": 42, "unprefixed": "value"}

        def get_query_fragment(self):
            return "customVar(p: $prefixed, u: $unprefixed)"

        def parse_response(self, root_data):
            return root_data.get("customVar")

    composer = GraphQLQueryComposer(blocks=[CustomVarBlock()], root_field="")
    query = composer.build_query()
    assert "$unprefixed: String!" in query
    assert "$prefixed: Int!" in query

    now = datetime.now(UTC)
    variables = composer.build_variables(now, home_id="home_1")
    assert variables.get("prefixed") == 42
    assert variables.get("unprefixed") == "value"
    assert "$prefixed" not in variables


def test_battery_blocks_malformed_items():
    """Test that malformed items with null keys or times are cleanly ignored."""
    savings_block = BatterySavingsBlock()
    parsed_savings = savings_block.parse_response(
        {
            "battery": {
                "aggregatedHistory": {
                    "periods": [
                        None,
                        {
                            "key": None,
                            "batteryValueItems": [{"kind": "TOTAL", "value": 1.0}],
                        },
                        {
                            "key": "TODAY",
                            "batteryValueItems": [{"kind": "TOTAL", "value": 15.0}],
                        },
                    ]
                }
            }
        }
    )
    assert None not in parsed_savings
    assert parsed_savings["TODAY"]["value"] == 15.0

    planned_block = BatteryPlannedBlock()
    parsed_planned = planned_block.parse_response(
        {
            "batteryTimeline": {
                "energyFlow": {
                    "items": [
                        None,
                        {"time": None, "charged": 1000},
                        {
                            "time": "2026-09-20T10:00:00Z",
                            "kind": "FORECAST",
                            "charged": 2000,
                        },
                    ]
                },
                "stateOfCharge": {
                    "items": [
                        None,
                        {"time": None, "stateOfCharge": 50},
                        {"time": "2026-09-20T10:00:00Z", "stateOfCharge": 80.0},
                    ]
                },
            }
        }
    )
    assert len(parsed_planned) == 1
    assert parsed_planned[0]["time"] == "2026-09-20T10:00:00Z"
    assert parsed_planned[0]["state_of_charge"] == 80.0
