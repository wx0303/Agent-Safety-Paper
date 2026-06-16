from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class RailType(str, Enum):
    INPUT = "input"
    PLANNER = "planner"
    RETRIEVAL = "retrieval"
    MEMORY = "memory"
    EXECUTION = "execution"
    OUTPUT = "output"
    AUDIT = "audit"
    MODEL = "model"
    DIALOG = "dialog"


@dataclass(frozen=True)
class AgentEvent:
    """Normalized runtime event inspected by AgentSec policies."""

    rail: RailType
    content: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    event_id: str | None = field(default_factory=lambda: str(uuid4()))
    session_id: str | None = None
    trace_id: str | None = None
    parent_event_id: str | None = None
    source: str | None = None
    target: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: Any | None = None
    retrieval_docs: list[dict[str, Any]] | None = None
    memory_key: str | None = None
    memory_value: Any | None = None
    risk_score: float | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    framework: str = "unknown"
    actor: str | None = None

    def with_content(self, content: Any) -> "AgentEvent":
        updates: dict[str, Any] = {"content": content}
        if self.retrieval_docs is not None and isinstance(content, list):
            updates["retrieval_docs"] = content
        if self.tool_args is not None and isinstance(content, dict):
            updates["tool_args"] = content
        if self.tool_result is not None or self.metadata.get("phase") == "tool_result":
            updates["tool_result"] = content
        if self.memory_value is not None:
            updates["memory_value"] = content
        return replace(self, **updates)

    def with_metadata(self, **metadata: Any) -> "AgentEvent":
        merged = {**self.metadata, **metadata}
        return replace(self, metadata=merged)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of this event."""

        return {
            "rail": self.rail.value,
            "content": self.content,
            "metadata": self.metadata,
            "event_id": self.event_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "parent_event_id": self.parent_event_id,
            "source": self.source,
            "target": self.target,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "tool_result": self.tool_result,
            "retrieval_docs": self.retrieval_docs,
            "memory_key": self.memory_key,
            "memory_value": self.memory_value,
            "risk_score": self.risk_score,
            "timestamp": self.timestamp.isoformat(),
            "framework": self.framework,
            "actor": self.actor,
        }

    @classmethod
    def from_text(
        cls,
        text: str,
        rail: RailType = RailType.INPUT,
        *,
        framework: str = "unknown",
        **metadata: Any,
    ) -> "AgentEvent":
        return cls(rail=rail, content=text, framework=framework, metadata=metadata)

    @classmethod
    def from_tool_call(
        cls,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        framework: str = "unknown",
        **metadata: Any,
    ) -> "AgentEvent":
        return cls(
            rail=RailType.EXECUTION,
            content=tool_args,
            framework=framework,
            target=tool_name,
            tool_name=tool_name,
            tool_args=tool_args,
            metadata={"tool_name": tool_name, **metadata},
        )

    @classmethod
    def from_tool_result(
        cls,
        tool_name: str,
        tool_result: Any,
        *,
        framework: str = "unknown",
        **metadata: Any,
    ) -> "AgentEvent":
        return cls(
            rail=RailType.EXECUTION,
            content=tool_result,
            framework=framework,
            target=tool_name,
            tool_name=tool_name,
            tool_result=tool_result,
            metadata={"tool_name": tool_name, "phase": "tool_result", **metadata},
        )

    @classmethod
    def from_retrieval(
        cls,
        docs: list[dict[str, Any]],
        *,
        framework: str = "unknown",
        **metadata: Any,
    ) -> "AgentEvent":
        return cls(
            rail=RailType.RETRIEVAL,
            content=docs,
            framework=framework,
            retrieval_docs=docs,
            metadata=metadata,
        )

    @classmethod
    def from_memory_write(
        cls,
        key: str,
        value: Any,
        *,
        scope: str,
        framework: str = "unknown",
        **metadata: Any,
    ) -> "AgentEvent":
        return cls(
            rail=RailType.MEMORY,
            content=value,
            framework=framework,
            target=scope,
            memory_key=key,
            memory_value=value,
            metadata={"scope": scope, **metadata},
        )
