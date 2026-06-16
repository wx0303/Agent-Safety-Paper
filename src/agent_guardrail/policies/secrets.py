from __future__ import annotations

import re
from dataclasses import dataclass, field

from agent_guardrail.decisions import Decision, DecisionAction, RiskLevel
from agent_guardrail.events import AgentEvent, RailType
from agent_guardrail.policies.base import Policy


@dataclass
class SecretRedactionPolicy(Policy):
    policy_id: str = "secret_redaction"
    rail_types: set[RailType] = field(default_factory=lambda: {RailType.INPUT, RailType.OUTPUT, RailType.EXECUTION})
    patterns: tuple[re.Pattern[str], ...] = field(
        default_factory=lambda: (
            re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{12,})['\"]?"),
            re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-.]{16,}"),
        )
    )

    def evaluate(self, event: AgentEvent) -> Decision:
        if not isinstance(event.content, str):
            return Decision.allow(self.policy_id)

        redacted = event.content
        for pattern in self.patterns:
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)

        if redacted == event.content:
            return Decision.allow(self.policy_id)
        return Decision(
            action=DecisionAction.FILTER,
            risk=RiskLevel.MEDIUM,
            reason="Secret-like content was filtered.",
            policy_id=self.policy_id,
            rewritten_content=redacted,
        )
