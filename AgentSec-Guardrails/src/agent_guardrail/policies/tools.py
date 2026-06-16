from __future__ import annotations

from dataclasses import dataclass, field

from agent_guardrail.decisions import Decision, DecisionAction, RiskLevel
from agent_guardrail.events import AgentEvent, RailType
from agent_guardrail.policies.base import Policy


@dataclass
class ToolAllowlistPolicy(Policy):
    allowed_tools: set[str]
    policy_id: str = "tool_allowlist"
    rail_types: set[RailType] = field(default_factory=lambda: {RailType.EXECUTION})

    def evaluate(self, event: AgentEvent) -> Decision:
        tool_name = event.target or event.metadata.get("tool_name")
        if tool_name in self.allowed_tools:
            return Decision.allow(self.policy_id)
        return Decision(
            action=DecisionAction.REQUIRE_HUMAN,
            risk=RiskLevel.HIGH,
            reason=f"Tool '{tool_name}' is not in the allowlist.",
            policy_id=self.policy_id,
        )

