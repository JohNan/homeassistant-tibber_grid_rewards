"""Modular GraphQL query block architecture for Tibber queries and telemetry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
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


class GenericQueryBlock(GraphQLQueryBlock):
    """Declarative, functional, or dynamic GraphQLQueryBlock.

    Allows defining any block inline without creating a subclass:
        block = GenericQueryBlock(
            name="solar",
            query_fragment="solar { currentPower }",
            parse_fn=lambda data: (data.get("solar") or {}).get("currentPower"),
        )
    """

    def __init__(
        self,
        name: str,
        query_fragment: str,
        parse_fn: Callable[[dict[str, Any]], Any] | None = None,
        root_field: str = "me.home",
        variable_definitions: dict[str, str] | None = None,
        variables_fn: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.name = name
        self.query_fragment = query_fragment.strip()
        self.parse_fn = parse_fn or (lambda d: d.get(name))
        self.root_field = root_field
        self._var_defs = variable_definitions or {}
        self._vars_fn = variables_fn

    def get_variable_definitions(self) -> dict[str, str]:
        return dict(self._var_defs)

    def get_variables(
        self, now: datetime, home_id: str, device_id: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        if self._vars_fn is not None:
            return self._vars_fn(
                now=now, home_id=home_id, device_id=device_id, **kwargs
            )
        return {}

    def get_query_fragment(self) -> str:
        return self.query_fragment

    def parse_response(self, root_data: dict[str, Any]) -> Any:
        return self.parse_fn(root_data)


def create_query_block(
    name: str,
    query_fragment: str,
    parse_fn: Callable[[dict[str, Any]], Any] | None = None,
    root_field: str = "me.home",
    variable_definitions: dict[str, str] | None = None,
    variables_fn: Callable[..., dict[str, Any]] | None = None,
) -> GenericQueryBlock:
    """Convenience factory to quickly define and instantiate any GraphQL query block."""
    return GenericQueryBlock(
        name=name,
        query_fragment=query_fragment,
        parse_fn=parse_fn,
        root_field=root_field,
        variable_definitions=variable_definitions,
        variables_fn=variables_fn,
    )


class QueryBlockRegistry:
    """Central registry of modular GraphQL query blocks."""

    def __init__(self) -> None:
        self._registry: dict[str, GraphQLQueryBlock | type[GraphQLQueryBlock]] = {}

    def register(
        self,
        block_or_cls: GraphQLQueryBlock | type[GraphQLQueryBlock],
        name: str | None = None,
    ) -> None:
        """Register a query block instance or class."""
        key = name or getattr(block_or_cls, "name", None)
        if not key:
            raise ValueError("Query block must specify a name")
        self._registry[key] = block_or_cls

    def get(self, name: str) -> GraphQLQueryBlock:
        """Retrieve an instantiated query block by name."""
        if name not in self._registry:
            raise KeyError(f"Query block '{name}' is not registered")
        item = self._registry[name]
        if isinstance(item, type):
            return item()
        return item

    def get_or_create(
        self, block_or_name: GraphQLQueryBlock | str
    ) -> GraphQLQueryBlock:
        """Return a block instance given either a block or registered name."""
        if hasattr(block_or_name, "get_query_fragment") and hasattr(
            block_or_name, "parse_response"
        ):
            return block_or_name  # type: ignore[return-value]
        if isinstance(block_or_name, str):
            return self.get(block_or_name)
        return block_or_name  # type: ignore[return-value]

    def list_blocks(self) -> list[str]:
        """List all registered block names."""
        return list(self._registry.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._registry


GLOBAL_QUERY_BLOCK_REGISTRY = QueryBlockRegistry()


class GraphQLQueryComposer:
    """Composes arbitrary modular GraphQL queries and coordinates response parsing."""

    def __init__(
        self,
        blocks: Sequence[GraphQLQueryBlock | str] | None = None,
        operation_name: str = "GetTelemetryDetails",
        root_field: str = "me.home",
        registry: QueryBlockRegistry | None = None,
    ) -> None:
        self._registry = registry or GLOBAL_QUERY_BLOCK_REGISTRY
        self.operation_name = operation_name
        self.root_field = root_field
        self._blocks: list[GraphQLQueryBlock] = []
        if blocks is not None:
            for b in blocks:
                self.add_block(b)

    @property
    def blocks(self) -> list[GraphQLQueryBlock]:
        """Return the registered query blocks."""
        return self._blocks

    def add_block(self, block: GraphQLQueryBlock | str) -> None:
        """Add a query block instance or registered block name to the composer."""
        resolved = self._registry.get_or_create(block)
        self._blocks.append(resolved)

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

        fragment_lines: list[str] = [
            block.get_query_fragment() for block in self._blocks
        ]
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
            variables.update(
                block.get_variables(now, home_id, device_id=device_id, **kwargs)
            )
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
                root_data = (data.get("me") or {}).get("home") or {}
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


def create_query_composer(
    blocks: Sequence[GraphQLQueryBlock | str] | None = None,
    operation_name: str = "GetTelemetryDetails",
    root_field: str = "me.home",
    registry: QueryBlockRegistry | None = None,
) -> GraphQLQueryComposer:
    """Helper to instantiate a GraphQLQueryComposer with blocks or block names."""
    return GraphQLQueryComposer(
        blocks=blocks,
        operation_name=operation_name,
        root_field=root_field,
        registry=registry,
    )
