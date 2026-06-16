from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from agent_guardrail.decisions import Decision, DecisionAction, RiskLevel
from agent_guardrail.events import AgentEvent, RailType
from agent_guardrail.policies.base import Policy


@dataclass
class ResearchDefensePolicy(Policy):
    """Template for adding a new paper/research-based defense method.

    Replace _detect_attack() with a classifier, ruleset, model score, external
    service call, or any newly published jailbreak defense algorithm.
    """

    policy_id: str = "research_defense_template"
    rail_types: set[RailType] = field(default_factory=lambda: {RailType.INPUT, RailType.DIALOG})
    threshold: float = 0.8

    def evaluate(self, event: AgentEvent) -> Decision:
        score = self._detect_attack(str(event.content), event)
        if score >= self.threshold:
            return Decision(
                action=DecisionAction.REQUIRE_HUMAN,
                risk=RiskLevel.HIGH,
                reason=f"Research defense score {score:.2f} exceeded threshold {self.threshold:.2f}; human review required.",
                policy_id=self.policy_id,
                metadata={"score": score, "threshold": self.threshold},
            )
        return Decision.allow(self.policy_id)

    def _detect_attack(self, text: str, event: AgentEvent) -> float:
        _ = event
        attack_markers = ("ignore previous", "disable guardrail", "developer mode", "exfiltrate")
        return 1.0 if any(marker in text.lower() for marker in attack_markers) else 0.0


@dataclass
class KeywordPolicy(Policy):
    policy_id: str
    keywords: Iterable[str]
    rail_types: set[RailType] = field(default_factory=lambda: {RailType.INPUT, RailType.OUTPUT, RailType.DIALOG})
    action: DecisionAction = DecisionAction.BLOCK
    risk: RiskLevel = RiskLevel.HIGH

    def evaluate(self, event: AgentEvent) -> Decision:
        text = str(event.content).lower()
        matched = [word for word in self.keywords if word.lower() in text]
        if not matched:
            return Decision.allow(self.policy_id)
        return Decision(
            action=self.action,
            risk=self.risk,
            reason=f"Matched forbidden keyword(s): {', '.join(matched)}",
            policy_id=self.policy_id,
        )
