from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePath

from agent_guardrail.decisions import Decision, DecisionAction, RiskLevel
from agent_guardrail.events import AgentEvent, RailType
from agent_guardrail.policies.base import Policy


@dataclass
class MemoryScopePolicy(Policy):
    allowed_roots: set[str]
    policy_id: str = "memory_scope"
    rail_types: set[RailType] = field(default_factory=lambda: {RailType.MEMORY})

    def evaluate(self, event: AgentEvent) -> Decision:
        path_value = event.target or event.metadata.get("path")
        if not path_value:
            return Decision(
                action=DecisionAction.REQUIRE_HUMAN,
                risk=RiskLevel.MEDIUM,
                reason="Memory write target is missing.",
                policy_id=self.policy_id,
            )

        target = PurePath(str(path_value))
        allowed = any(str(target).startswith(root) for root in self.allowed_roots)
        if allowed:
            return Decision.allow(self.policy_id)
        return Decision(
            action=DecisionAction.BLOCK,
            risk=RiskLevel.CRITICAL,
            reason=f"Memory write target '{target}' is outside allowed roots.",
            policy_id=self.policy_id,
        )

