from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_guardrail.decisions import Decision, DecisionType, RiskLevel
from agent_guardrail.events import AgentEvent, RailType
from agent_guardrail.policies.base import Policy
from agent_guardrail.policies.patterns import redact_secrets


SYSTEM_PROMPT_LEAK_MARKERS = (
    "system prompt:",
    "developer message:",
    "hidden instruction",
    "internal policy",
    "original system message",
    "系统提示词",
    "开发者消息",
)

INTERNAL_TRACE_MARKERS = (
    "tool_result",
    "trace_id",
    "parent_event_id",
    "internal execution log",
    "raw tool output",
)

PII_PATTERNS = (
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
)


@dataclass
class OutputSafetyPolicy(Policy):
    """Output guard that blocks prompt leakage and redacts sensitive final content."""

    policy_id: str = "output_safety"
    rail_types: set[RailType] = field(default_factory=lambda: {RailType.OUTPUT})

    def evaluate(self, event: AgentEvent) -> Decision:
        text = str(event.content)
        lower = text.lower()
        leaks = [marker for marker in SYSTEM_PROMPT_LEAK_MARKERS if marker.lower() in lower]
        if leaks:
            return Decision(
                DecisionType.BLOCK,
                risk=RiskLevel.CRITICAL,
                reason=f"Final output appears to leak system/developer instructions: {', '.join(leaks)}",
                policy_id=self.policy_id,
                metadata={"matches": leaks},
            )

        redacted, changed = redact_secrets(text)
        if changed:
            return Decision.filter(
                risk=RiskLevel.MEDIUM,
                reason="Final output contained secret-like content and was filtered.",
                policy_id=self.policy_id,
                rewritten_content=redacted,
            )

        pii_redacted = text
        for pattern in PII_PATTERNS:
            pii_redacted = pattern.sub("[REDACTED_PII]", pii_redacted)
        if pii_redacted != text:
            return Decision.filter(
                risk=RiskLevel.MEDIUM,
                reason="Final output contained personal information and was filtered.",
                policy_id=self.policy_id,
                rewritten_content=pii_redacted,
            )

        internal_markers = [marker for marker in INTERNAL_TRACE_MARKERS if marker in lower]
        if internal_markers:
            filtered = text
            for marker in internal_markers:
                filtered = re.sub(re.escape(marker), "[FILTERED_INTERNAL_TRACE]", filtered, flags=re.IGNORECASE)
            return Decision.filter(
                risk=RiskLevel.MEDIUM,
                reason="Final output exposed internal tool or trace details and was filtered.",
                policy_id=self.policy_id,
                rewritten_content=filtered,
                metadata={"matches": internal_markers},
            )

        return Decision.allow(self.policy_id)


@dataclass
class AuditLoggingPolicy(Policy):
    """In-memory and optional JSONL audit logger for event and decision traces."""

    log_path: str | None = None
    policy_id: str = "audit_logging"
    rail_types: set[RailType] = field(
        default_factory=lambda: {
            RailType.INPUT,
            RailType.PLANNER,
            RailType.RETRIEVAL,
            RailType.MEMORY,
            RailType.EXECUTION,
            RailType.OUTPUT,
            RailType.AUDIT,
        }
    )
    records: list[dict[str, Any]] = field(default_factory=list)

    def evaluate(self, event: AgentEvent) -> Decision:
        _ = event
        return Decision.allow(self.policy_id)

    def record_decision(self, event: AgentEvent, decision: Decision) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event_id": event.event_id,
            "trace_id": event.trace_id,
            "rail": event.rail.value,
            "policy": decision.policy_name,
            "decision": decision.decision.value,
            "reason": decision.reason,
            "severity": decision.severity,
            "metadata": decision.metadata,
        }
        self.records.append(record)
        if self.log_path:
            path = Path(self.log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
