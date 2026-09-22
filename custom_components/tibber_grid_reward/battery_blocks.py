"""Modular battery telemetry query blocks for Tibber home batteries."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from .query_blocks import (
    GLOBAL_QUERY_BLOCK_REGISTRY,
    GraphQLQueryBlock,
    GraphQLQueryComposer,
)

# Backward compatibility alias
BatteryDataBlock = GraphQLQueryBlock


class BatteryQueryComposer(GraphQLQueryComposer):
    """Composer specifically tailored for battery telemetry with default blocks."""

    def __init__(
        self,
        blocks: Sequence[GraphQLQueryBlock | str] | None = None,
        operation_name: str = "GetBatteryDetails",
    ) -> None:
        super().__init__(
            blocks=blocks if blocks is not None else list(DEFAULT_BATTERY_BLOCKS),
            operation_name=operation_name,
            root_field="me.home",
        )


class BatterySavingsBlock(GraphQLQueryBlock):
    """Telemetry block for aggregated battery savings (TODAY, WEEK, MONTH)."""

    name = "savings"
    root_field = "me.home"

    def get_query_fragment(self) -> str:
        return """battery(id: $deviceId) {
  aggregatedHistory {
    periods {
      key
      batteryValueItems {
        value
        unit
        kind
      }
    }
  }
}"""

    def parse_response(self, root_data: dict[str, Any]) -> dict[str, Any]:
        battery_data = root_data.get("battery") or {}
        periods = (battery_data.get("aggregatedHistory") or {}).get("periods") or []
        savings: dict[str, Any] = {}
        for period in periods:
            if not isinstance(period, dict):
                continue
            key = period.get("key")
            if not key:
                continue
            for item in period.get("batteryValueItems") or []:
                if isinstance(item, dict) and item.get("kind") == "TOTAL":
                    savings[key] = item
                    break
        return savings


class BatteryActivityBlock(GraphQLQueryBlock):
    """Telemetry block for battery activity intervals and reason typenames."""

    name = "activity"
    root_field = "me.home"

    def __init__(self, hours_back: int = 6) -> None:
        self.hours_back = hours_back

    def get_variable_definitions(self) -> dict[str, str]:
        return {
            "$activityFrom": "DateTime!",
            "$activityTo": "DateTime!",
        }

    def get_variables(
        self, now: datetime, home_id: str, device_id: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        return {
            "activityFrom": (now - timedelta(hours=self.hours_back)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "activityTo": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def get_query_fragment(self) -> str:
        return """batteryActivityHistory(id: $deviceId, from: $activityFrom, to: $activityTo) {
  items {
    from
    to
    reason {
      __typename
    }
    secondaryReason {
      __typename
    }
  }
}"""

    def parse_response(self, root_data: dict[str, Any]) -> list[dict[str, Any]]:
        activity_history = root_data.get("batteryActivityHistory") or {}
        return activity_history.get("items") or []


class BatteryPlannedBlock(GraphQLQueryBlock):
    """Telemetry block for quarter-hourly planned timeline and state of charge."""

    name = "planned"
    root_field = "me.home"

    def __init__(self, days_ahead: int = 1, resolution: str = "QUARTER_HOURLY") -> None:
        self.days_ahead = days_ahead
        self.resolution = resolution

    def get_variable_definitions(self) -> dict[str, str]:
        return {
            "$timelineFrom": "DateTime!",
            "$timelineTo": "DateTime!",
            "$resolution": "BatteryTimelineResolution!",
        }

    def get_variables(
        self, now: datetime, home_id: str, device_id: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        timeline_end = (now + timedelta(days=self.days_ahead)).replace(
            hour=23, minute=59, second=59, microsecond=0
        )
        return {
            "timelineFrom": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timelineTo": timeline_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "resolution": self.resolution,
        }

    def get_query_fragment(self) -> str:
        return """batteryTimeline(
  id: $deviceId,
  from: $timelineFrom,
  to: $timelineTo,
  resolution: $resolution
) {
  energyFlow {
    items {
      kind
      time
      charged
      discharged
    }
  }
  stateOfCharge {
    items {
      kind
      time
      stateOfCharge
    }
  }
}"""

    def parse_response(self, root_data: dict[str, Any]) -> list[dict[str, Any]]:
        timeline = root_data.get("batteryTimeline") or {}
        soc_by_time = {
            item.get("time"): item.get("stateOfCharge")
            for item in ((timeline.get("stateOfCharge") or {}).get("items") or [])
            if isinstance(item, dict) and item.get("time")
        }
        planned: list[dict[str, Any]] = []
        for item in (timeline.get("energyFlow") or {}).get("items") or []:
            if not isinstance(item, dict) or not item.get("time"):
                continue
            planned.append(
                {
                    "time": item.get("time"),
                    "kind": item.get("kind"),
                    "charged": item.get("charged"),
                    "discharged": item.get("discharged"),
                    "state_of_charge": soc_by_time.get(item.get("time")),
                }
            )
        return planned


DEFAULT_BATTERY_BLOCKS: tuple[GraphQLQueryBlock, ...] = (
    BatterySavingsBlock(),
    BatteryActivityBlock(),
    BatteryPlannedBlock(),
)

# Register pre-made battery blocks in the global registry
GLOBAL_QUERY_BLOCK_REGISTRY.register(BatterySavingsBlock, "savings")
GLOBAL_QUERY_BLOCK_REGISTRY.register(BatteryActivityBlock, "activity")
GLOBAL_QUERY_BLOCK_REGISTRY.register(BatteryPlannedBlock, "planned")


def create_battery_query_composer(
    blocks: Sequence[GraphQLQueryBlock | str] | None = None,
) -> GraphQLQueryComposer:
    """Helper to instantiate a composer for battery telemetry."""
    return GraphQLQueryComposer(
        blocks=blocks if blocks is not None else DEFAULT_BATTERY_BLOCKS,
        operation_name="GetBatteryDetails",
        root_field="me.home",
    )
