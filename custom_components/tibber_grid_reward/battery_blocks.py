"""Modular query blocks for Tibber battery telemetry."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, ClassVar


class BatteryDataBlock(ABC):
    """Abstract block representing a modular GraphQL telemetry query and response parser."""

    name: ClassVar[str]

    def get_variable_definitions(self) -> dict[str, str]:
        """Return GraphQL variable definitions needed by this block."""
        return {}

    def get_variables(
        self, now: datetime, home_id: str, battery_id: str
    ) -> dict[str, Any]:
        """Return variable values for this block."""
        return {}

    @abstractmethod
    def get_query_fragment(self) -> str:
        """Return GraphQL query snippet to embed inside me.home(id: $homeId)."""

    @abstractmethod
    def parse_response(self, home_data: dict[str, Any]) -> Any:
        """Parse the GraphQL home_data payload into structured data for this block."""


class BatterySavingsBlock(BatteryDataBlock):
    """Telemetry block for aggregated battery savings (TODAY, WEEK, MONTH)."""

    name = "savings"

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

    def parse_response(self, home_data: dict[str, Any]) -> dict[str, Any]:
        battery_data = home_data.get("battery") or {}
        periods = (battery_data.get("aggregatedHistory") or {}).get("periods") or []
        savings: dict[str, Any] = {}
        for period in periods:
            for item in period.get("batteryValueItems") or []:
                if item.get("kind") == "TOTAL":
                    savings[period.get("key")] = item
                    break
        return savings


class BatteryActivityBlock(BatteryDataBlock):
    """Telemetry block for battery activity intervals and reason typenames."""

    name = "activity"

    def __init__(self, hours_back: int = 6) -> None:
        self.hours_back = hours_back

    def get_variable_definitions(self) -> dict[str, str]:
        return {
            "$activityFrom": "DateTime!",
            "$activityTo": "DateTime!",
        }

    def get_variables(
        self, now: datetime, home_id: str, battery_id: str
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

    def parse_response(self, home_data: dict[str, Any]) -> list[dict[str, Any]]:
        activity_history = home_data.get("batteryActivityHistory") or {}
        return activity_history.get("items") or []


class BatteryPlannedBlock(BatteryDataBlock):
    """Telemetry block for quarter-hourly planned timeline and state of charge."""

    name = "planned"

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
        self, now: datetime, home_id: str, battery_id: str
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

    def parse_response(self, home_data: dict[str, Any]) -> list[dict[str, Any]]:
        timeline = home_data.get("batteryTimeline") or {}
        soc_by_time = {
            item.get("time"): item.get("stateOfCharge")
            for item in ((timeline.get("stateOfCharge") or {}).get("items") or [])
        }
        planned: list[dict[str, Any]] = []
        for item in (timeline.get("energyFlow") or {}).get("items") or []:
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


DEFAULT_BATTERY_BLOCKS: tuple[BatteryDataBlock, ...] = (
    BatterySavingsBlock(),
    BatteryActivityBlock(),
    BatteryPlannedBlock(),
)


class BatteryQueryComposer:
    """Composes modular GraphQL queries and coordinates response parsing."""

    def __init__(self, blocks: Sequence[BatteryDataBlock] | None = None) -> None:
        self._blocks: list[BatteryDataBlock] = (
            list(blocks) if blocks is not None else list(DEFAULT_BATTERY_BLOCKS)
        )

    @property
    def blocks(self) -> list[BatteryDataBlock]:
        """Return the registered telemetry blocks."""
        return self._blocks

    def add_block(self, block: BatteryDataBlock) -> None:
        """Add a telemetry block to the composer."""
        self._blocks.append(block)

    def build_query(self) -> str:
        """Construct the full GraphQL query string from registered blocks."""
        var_defs: dict[str, str] = {
            "$homeId": "String!",
            "$deviceId": "String!",
        }
        for block in self._blocks:
            var_defs.update(block.get_variable_definitions())

        var_list = ", ".join(f"{k}: {v}" for k, v in var_defs.items())
        fragment_lines: list[str] = [block.get_query_fragment() for block in self._blocks]

        body = "\n".join(
            "      " + line if line.strip() else line
            for frag in fragment_lines
            for line in frag.splitlines()
        )

        return f"""query GetBatteryDetails({var_list}) {{
  me {{
    home(id: $homeId) {{
{body}
    }}
  }}
}}"""

    def build_variables(
        self, now: datetime, home_id: str, battery_id: str
    ) -> dict[str, Any]:
        """Construct merged variables dictionary from registered blocks."""
        variables: dict[str, Any] = {
            "homeId": home_id,
            "deviceId": battery_id,
        }
        for block in self._blocks:
            variables.update(block.get_variables(now, home_id, battery_id))
        return variables

    def parse_response(self, home_data: dict[str, Any]) -> dict[str, Any]:
        """Parse raw GraphQL me.home data using each block's parser."""
        return {block.name: block.parse_response(home_data) for block in self._blocks}
