"""Vendored wire contract — the SDK's own copy of the event/decision types.

This module is **pure stdlib, zero dependencies**. It is the single source of
truth for what the SDK sends to and parses back from an ``agentsec-server``
(``AgentEvent.to_dict()`` out, ``Decision.from_dict()`` in). It deliberately
does **not** import ``agent_guardrail`` — the SDK no longer depends on the core
engine; the server is expected to conform to the JSON shapes defined here.

Field names and enum serializations follow ``docs/sdk-api.md`` §2/§6 and
``docs/sdk-config.md`` §7. Keep this file and the server's serialization in
lockstep; ``tests/test_wire_contract.py`` guards the round trip.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any

__all__ = [
    "RailType",
    "DecisionType",
    "RiskLevel",
    "AgentEvent",
    "Decision",
]


class RailType(Enum):
    """The agent lifecycle point an event belongs to (wire value = lowercase)."""

    INPUT = "input"
    PLANNER = "planner"
    RETRIEVAL = "retrieval"
    MEMORY = "memory"
    EXECUTION = "execution"
    OUTPUT = "output"
    AUDIT = "audit"
    MODEL = "model"
    DIALOG = "dialog"


class DecisionType(Enum):
    """The verdict a policy returns (wire value = lowercase)."""

    ALLOW = "allow"
    REWRITE = "rewrite"
    DEGRADE = "degrade"
    REQUIRE_HUMAN = "require_human"
    BLOCK = "block"


class RiskLevel(Enum):
    """Severity band of a decision (wire value = lowercase)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_SEVERITY: dict[RiskLevel, int] = {
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}

# Identity/correlation fields that may be passed as keyword args to the
# ``AgentEvent.from_*`` factories; everything else lands in ``metadata``.
_CORRELATION = ("session_id", "trace_id", "parent_event_id", "actor", "source")


def _split_kwargs(kwargs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Partition factory kwargs into recognized correlation fields vs metadata."""

    correlation = {k: kwargs[k] for k in _CORRELATION if k in kwargs}
    metadata = {k: v for k, v in kwargs.items() if k not in _CORRELATION}
    return correlation, metadata


def _to_rail(value: Any) -> RailType:
    return value if isinstance(value, RailType) else RailType(value)


def _to_decision_type(value: Any) -> DecisionType:
    return value if isinstance(value, DecisionType) else DecisionType(value)


def _to_risk(value: Any) -> RiskLevel:
    return value if isinstance(value, RiskLevel) else RiskLevel(value)


# Optional event fields emitted on the wire only when set (keeps payloads small).
_OPTIONAL_EVENT_FIELDS = (
    "tool_name",
    "tool_args",
    "tool_result",
    "memory_key",
    "memory_value",
    "memory_scope",
    "retrieval_docs",
    "session_id",
    "trace_id",
    "parent_event_id",
    "actor",
    "source",
)


@dataclass
class AgentEvent:
    """One serializable agent event sent to the decision point.

    ``content`` is polymorphic by rail: ``str`` for INPUT/OUTPUT/PLANNER, the
    args ``dict`` (or result) for EXECUTION, ``list[dict]`` for RETRIEVAL, the
    stored value for MEMORY. The rail-specific factories below set the right
    typed fields alongside ``content`` so the server can read either.
    """

    rail: RailType
    content: Any = None
    framework: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: Any = None
    memory_key: str | None = None
    memory_value: Any = None
    memory_scope: str | None = None
    retrieval_docs: list[dict[str, Any]] | None = None
    session_id: str | None = None
    trace_id: str | None = None
    parent_event_id: str | None = None
    actor: str | None = None
    source: str | None = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)

    # ------------------------------------------------------------- factories

    @classmethod
    def from_text(
        cls, text: str, rail: RailType, *, framework: str = "unknown", **metadata: Any
    ) -> "AgentEvent":
        correlation, meta = _split_kwargs(metadata)
        return cls(
            rail=_to_rail(rail),
            content=text,
            framework=framework,
            metadata=meta,
            **correlation,
        )

    @classmethod
    def from_tool_call(
        cls,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        framework: str = "unknown",
        **metadata: Any,
    ) -> "AgentEvent":
        correlation, meta = _split_kwargs(metadata)
        return cls(
            rail=RailType.EXECUTION,
            content=tool_args,
            framework=framework,
            tool_name=tool_name,
            tool_args=tool_args,
            metadata=meta,
            **correlation,
        )

    @classmethod
    def from_tool_result(
        cls,
        tool_name: str,
        result: Any,
        *,
        framework: str = "unknown",
        **metadata: Any,
    ) -> "AgentEvent":
        correlation, meta = _split_kwargs(metadata)
        return cls(
            rail=RailType.EXECUTION,
            content=result,
            framework=framework,
            tool_name=tool_name,
            tool_result=result,
            metadata=meta,
            **correlation,
        )

    @classmethod
    def from_retrieval(
        cls,
        docs: list[dict[str, Any]],
        *,
        framework: str = "unknown",
        **metadata: Any,
    ) -> "AgentEvent":
        correlation, meta = _split_kwargs(metadata)
        return cls(
            rail=RailType.RETRIEVAL,
            content=docs,
            framework=framework,
            retrieval_docs=docs,
            metadata=meta,
            **correlation,
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
        correlation, meta = _split_kwargs(metadata)
        return cls(
            rail=RailType.MEMORY,
            content=value,
            framework=framework,
            memory_key=key,
            memory_value=value,
            memory_scope=scope,
            metadata=meta,
            **correlation,
        )

    # ------------------------------------------------------------- serialization

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "rail": self.rail.value,
            "content": self.content,
            "framework": self.framework,
            "metadata": dict(self.metadata),
        }
        for name in _OPTIONAL_EVENT_FIELDS:
            value = getattr(self, name)
            if value is not None:
                payload[name] = value
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentEvent":
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known and k != "rail"}
        return cls(rail=_to_rail(data["rail"]), **kwargs)


@dataclass
class Decision:
    """The verdict returned for an event. ``severity`` is derived from ``risk``."""

    decision: DecisionType
    reason: str = ""
    policy_name: str | None = None
    rewritten_content: Any = None
    risk: RiskLevel = RiskLevel.LOW
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def severity(self) -> int:
        """0–4 severity, larger = more severe. Derived from ``risk``."""

        return _SEVERITY.get(self.risk, 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reason": self.reason,
            "policy_name": self.policy_name,
            "rewritten_content": self.rewritten_content,
            "risk": self.risk.value,
            "severity": self.severity,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Decision":
        return cls(
            decision=_to_decision_type(data["decision"]),
            reason=data.get("reason", ""),
            policy_name=data.get("policy_name"),
            rewritten_content=data.get("rewritten_content"),
            risk=_to_risk(data.get("risk", "low")),
            metadata=dict(data.get("metadata") or {}),
        )
