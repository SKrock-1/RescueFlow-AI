"""
RescueFlow AI — Tool Registry.

Registers Python tool functions, auto-generates OpenAI-compatible
tool schemas, dispatches calls by name, and enforces the whitelist.
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any, Callable, get_type_hints

from app.errors import ToolNotFoundError, InvalidArgumentsError, ToolExecutionError

logger = logging.getLogger(__name__)

# Python type → JSON Schema type mapping
_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


class ToolRegistry:
    """
    Central registry for all agent-callable tools.

    Features:
    - Whitelist enforcement (only registered tools can be called)
    - Auto-generated OpenAI function-calling schemas
    - Read vs. mutation tool separation
    - Argument validation
    - Structured logging
    """

    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}
        self._schemas: dict[str, dict[str, Any]] = {}
        self._mutation_tools: set[str] = set()

    def register(
        self,
        func: Callable[..., Any],
        *,
        mutation: bool = False,
    ) -> Callable[..., Any]:
        """
        Register a tool function.

        Args:
            func: The Python function to register.
            mutation: True if this tool modifies state.

        Returns:
            The original function (for decorator chaining).
        """
        name = func.__name__
        self._tools[name] = func

        if mutation:
            self._mutation_tools.add(name)

        # Build OpenAI-compatible schema from signature + docstring
        self._schemas[name] = self._build_schema(func)
        logger.debug("Registered tool: %s (mutation=%s)", name, mutation)
        return func

    def get_tool(self, name: str) -> Callable[..., Any]:
        """Look up a registered tool by name."""
        if name not in self._tools:
            raise ToolNotFoundError(name)
        return self._tools[name]

    def is_mutation(self, name: str) -> bool:
        """Return True if the tool modifies state."""
        return name in self._mutation_tools

    def list_names(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())

    def get_openai_tools(self) -> list[dict[str, Any]]:
        """Return schemas in OpenAI function-calling format."""
        return [
            {"type": "function", "function": schema}
            for schema in self._schemas.values()
        ]

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a registered tool with validated arguments.

        Args:
            name: Tool name.
            arguments: Keyword arguments for the tool.

        Returns:
            JSON-serializable dict from the tool.

        Raises:
            ToolNotFoundError: Unknown tool.
            InvalidArgumentsError: Argument validation failure.
            ToolExecutionError: Runtime error inside the tool.
        """
        func = self.get_tool(name)

        # Validate required arguments
        sig = inspect.signature(func)
        for param_name, param in sig.parameters.items():
            if param.default is inspect.Parameter.empty and param_name not in arguments:
                raise InvalidArgumentsError(name, f"Missing required argument: '{param_name}'")

        # Execute
        logger.info("Executing tool: %s(%s)", name, json.dumps(arguments, default=str)[:200])
        try:
            result = func(**arguments)
        except (ToolNotFoundError, InvalidArgumentsError):
            raise
        except Exception as exc:
            logger.exception("Tool '%s' raised an exception", name)
            raise ToolExecutionError(name, str(exc)) from exc

        # Ensure result is a dict
        if not isinstance(result, dict):
            result = {"result": result}

        return result

    # ──────────────────────────────────────────
    # Schema Generation
    # ──────────────────────────────────────────

    @staticmethod
    def _build_schema(func: Callable[..., Any]) -> dict[str, Any]:
        """Build an OpenAI function schema from the function signature."""
        sig = inspect.signature(func)
        hints = get_type_hints(func)

        doc = inspect.getdoc(func) or ""
        description = doc.split("\n\n")[0].strip()  # First paragraph

        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            ptype = hints.get(param_name, str)
            json_type = _TYPE_MAP.get(ptype, "string")
            prop: dict[str, Any] = {"type": json_type, "description": param_name}

            # Extract per-param docs from docstring (best-effort)
            for line in doc.split("\n"):
                stripped = line.strip()
                if stripped.lower().startswith(param_name):
                    prop["description"] = stripped
                    break

            properties[param_name] = prop

            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        schema: dict[str, Any] = {
            "name": func.__name__,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
        return schema


# ────────────────────────────────────────────
# Global registry instance
# ────────────────────────────────────────────
registry = ToolRegistry()
