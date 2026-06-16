from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolRequest:
    """Normalized tool intent requested by an agent runtime."""

    name: str
    args: dict[str, Any]
    intent: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_args(self, args: dict[str, Any]) -> "ToolRequest":
        return replace(self, args=args)


@dataclass(frozen=True)
class ToolExecutionResult:
    request: ToolRequest
    output: Any


class ToolExecutor(Protocol):
    """Protocol implemented by tool registries or framework-specific adapters."""

    def execute(self, request: ToolRequest) -> Any:
        ...


class ToolExecutionError(RuntimeError):
    pass


@dataclass
class ToolRegistry:
    """Simple callable-backed tool executor."""

    _tools: dict[str, Callable[[dict[str, Any]], Any]] = field(default_factory=dict)

    def register(
        self,
        name: str,
        func: Callable[[dict[str, Any]], Any] | None = None,
    ) -> Callable[[dict[str, Any]], Any]:
        if func is None:
            def decorator(actual: Callable[[dict[str, Any]], Any]) -> Callable[[dict[str, Any]], Any]:
                self._tools[name] = actual
                return actual

            return decorator

        self._tools[name] = func
        return func

    def execute(self, request: ToolRequest) -> Any:
        try:
            tool = self._tools[request.name]
        except KeyError as exc:
            raise ToolExecutionError(f"Tool {request.name!r} is not registered.") from exc
        return tool(request.args)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def __contains__(self, name: str) -> bool:
        return name in self._tools
