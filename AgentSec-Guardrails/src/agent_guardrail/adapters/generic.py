from __future__ import annotations

from typing import Any

from agent_guardrail.events import AgentEvent, RailType


class EventAdapter:
    framework: str

    def input_event(self, content: Any, **metadata: Any) -> AgentEvent:
        return AgentEvent.from_text(content, RailType.INPUT, framework=self.framework, **metadata)

    def model_event(self, content: Any, phase: str, **metadata: Any) -> AgentEvent:
        return AgentEvent(
            rail=RailType.MODEL,
            content=content,
            framework=self.framework,
            metadata={"phase": phase, **metadata},
        )

    def tool_call_event(self, tool_name: str, arguments: dict[str, Any], **metadata: Any) -> AgentEvent:
        return AgentEvent.from_tool_call(tool_name, arguments, framework=self.framework, **metadata)

    def tool_result_event(self, tool_name: str, result: Any, **metadata: Any) -> AgentEvent:
        return AgentEvent.from_tool_result(tool_name, result, framework=self.framework, **metadata)

    def retrieval_result_event(self, content: Any, source: str, **metadata: Any) -> AgentEvent:
        return AgentEvent.from_retrieval(
            [{"text": content, "source": source, **metadata}],
            framework=self.framework,
        )

    def memory_write_event(self, content: Any, path: str, **metadata: Any) -> AgentEvent:
        return AgentEvent.from_memory_write(
            path,
            content,
            scope=str(metadata.pop("scope", path)),
            framework=self.framework,
            path=path,
            **metadata,
        )

    def output_event(self, content: Any, **metadata: Any) -> AgentEvent:
        return AgentEvent.from_text(content, RailType.OUTPUT, framework=self.framework, **metadata)


class OpenClawAdapter(EventAdapter):
    framework = "openclaw"


class HermesAdapter(EventAdapter):
    framework = "hermes"


class MCPAgentAdapter(EventAdapter):
    framework = "mcp-agent"
