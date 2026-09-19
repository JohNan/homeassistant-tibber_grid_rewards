"""Modular GraphQL query block architecture for Tibber queries and telemetry."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from typing import Any, ClassVar


class GraphQLQueryBlock(ABC):
    """Abstract block representing a modular GraphQL query and response parser."""

    name: ClassVar[str]
    root_field: ClassVar[str] = "me.home"

    def get_variable_definitions(self) -> dict[str, str]:
        """Return GraphQL variable definitions needed by this block (e.g. {'$activityFrom': 'DateTime!'})."""
        return {}

    def get_variables(
        self, now: datetime, home_id: str, device_id: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Return variable values for this block."""
        return {}

    @abstractmethod
    def get_query_fragment(self) -> str:
        """Return GraphQL query snippet to embed in the query root."""

    @abstractmethod
    def parse_response(self, root_data: dict[str, Any]) -> Any:
        """Parse the raw GraphQL root data into structured data for this block."""


class GraphQLQueryComposer:
    """Composes arbitrary modular GraphQL queries and coordinates response parsing."""

    def __init__(
        self,
        blocks: Sequence[GraphQLQueryBlock] | None = None,
        operation_name: str = "GetTelemetryDetails",
        root_field: str = "me.home",
    ) -> None:
        self._blocks: list[GraphQLQueryBlock] = list(blocks) if blocks is not None else []
        self.operation_name = operation_name
        self.root_field = root_field

    @property
    def blocks(self) -> list[GraphQLQueryBlock]:
        """Return the registered query blocks."""
        return self._blocks

    def add_block(self, block: GraphQLQueryBlock) -> None:
        """Add a query block to the composer."""
        self._blocks.append(block)

    def build_query(self) -> str:
        """Construct the full GraphQL query string from registered blocks."""
        var_defs: dict[str, str] = {}
        if self.root_field in ("me.home", "home"):
            var_defs["$homeId"] = "String!"
            if any(
                "$deviceId" in b.get_query_fragment()
                or "$deviceId" in b.get_variable_definitions()
                for b in self._blocks
            ):
                var_defs["$deviceId"] = "String!"

        for block in self._blocks:
            var_defs.update(block.get_variable_definitions())

        var_list = ", ".join(f"{k}: {v}" for k, v in var_defs.items())
        header = (
            f"query {self.operation_name}({var_list})"
            if var_list
            else f"query {self.operation_name}"
        )

        fragment_lines: list[str] = [block.get_query_fragment() for block in self._blocks]
        inner_body = "\n".join(
            "      " + line if line.strip() else line
            for frag in fragment_lines
            for line in frag.splitlines()
        )

        if self.root_field == "me.home":
            return f"""{header} {{
  me {{
    home(id: $homeId) {{
{inner_body}
    }}
  }}
}}"""
        elif self.root_field == "home":
            return f"""{header} {{
  home(id: $homeId) {{
{inner_body}
  }}
}}"""
        elif self.root_field == "me":
            return f"""{header} {{
  me {{
{inner_body}
  }}
}}"""
        return f"""{header} {{
{inner_body}
}}"""

    def build_variables(
        self, now: datetime, home_id: str, device_id: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Construct merged variables dictionary from registered blocks."""
        variables: dict[str, Any] = {}
        if self.root_field in ("me.home", "home"):
            variables["homeId"] = home_id
            if device_id is not None:
                variables["deviceId"] = device_id

        for block in self._blocks:
            variables.update(block.get_variables(now, home_id, device_id=device_id, **kwargs))
        return variables

    def parse_response(self, response_data: dict[str, Any]) -> dict[str, Any]:
        """Parse raw GraphQL response data navigating root_field and delegating to blocks."""
        data = (
            response_data.get("data")
            if isinstance(response_data, dict) and "data" in response_data
            else response_data
        )
        root_data: dict[str, Any] = data
        if self.root_field == "me.home":
            if "me" in data:
                root_data = ((data.get("me") or {}).get("home") or {})
            elif "home" in data:
                root_data = data.get("home") or {}
            else:
                # Already unwrapped to home_data
                root_data = data
        elif self.root_field == "home" and "home" in data:
            root_data = data.get("home") or {}
        elif self.root_field == "me" and "me" in data:
            root_data = data.get("me") or {}

        return {block.name: block.parse_response(root_data) for block in self._blocks}
