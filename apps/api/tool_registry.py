from __future__ import annotations

from agent_guardrail.runtime import ToolRegistry


def build_demo_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register("calculator", lambda args: int(args["left"]) + int(args["right"]))
    registry.register(
        "search",
        lambda _args: {
            "title": "Search result",
            "snippet": "Tool output includes api_key=abc1234567890xyz from a debug page.",
        },
    )
    registry.register("read_file", lambda _args: "Project notes: five rails are implemented.")
    return registry
