from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DecisionType(str, Enum):
    ALLOW = "allow"
    FILTER = "filter"
    BLOCK = "block"
    REWRITE = "rewrite"
    DEGRADE = "degrade"
    REQUIRE_HUMAN = "require_human"


# Backward-compatible name used by the original prototype.
DecisionAction = DecisionType


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


DECISION_SEVERITY = {
    DecisionType.ALLOW: 0,
    DecisionType.FILTER: 1,
    DecisionType.REWRITE: 1,
    DecisionType.DEGRADE: 2,
    DecisionType.REQUIRE_HUMAN: 3,
    DecisionType.BLOCK: 4,
}

RISK_RESPONSE_STRATEGY = {
    RiskLevel.LOW: DecisionType.ALLOW,
    RiskLevel.MEDIUM: DecisionType.FILTER,
    RiskLevel.HIGH: DecisionType.REQUIRE_HUMAN,
    RiskLevel.CRITICAL: DecisionType.BLOCK,
}


@dataclass(init=False)
class Decision:
    """Policy decision with compatibility aliases for the original API."""

    decision: DecisionType
    reason: str = ""
    policy_name: str | None = None
    severity: int = 0
    rewritten_content: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    risk: RiskLevel = RiskLevel.LOW

    def __init__(
        self,
        decision: DecisionType | str | None = None,
        *,
        action: DecisionType | str | None = None,
        reason: str = "",
        policy_name: str | None = None,
        policy_id: str | None = None,
        severity: int | None = None,
        rewritten_content: Any | None = None,
        metadata: dict[str, Any] | None = None,
        risk: RiskLevel | str = RiskLevel.LOW,
    ) -> None:
        selected = decision if decision is not None else action
        self.decision = DecisionType(selected or DecisionType.ALLOW)
        self.reason = reason
        self.policy_name = policy_name or policy_id
        self.risk = RiskLevel(risk)
        self.severity = severity if severity is not None else DECISION_SEVERITY[self.decision]
        self.rewritten_content = rewritten_content
        self.metadata = metadata or {}

    @property
    def action(self) -> DecisionType:
        """Backward-compatible alias for decision."""

        return self.decision

    @property
    def policy_id(self) -> str | None:
        """Backward-compatible alias for policy_name."""

        return self.policy_name

    @classmethod
    def allow(cls, policy_name: str | None = None, *, policy_id: str | None = None) -> "Decision":
        return cls(DecisionType.ALLOW, policy_name=policy_name or policy_id)

    @classmethod
    def filter(
        cls,
        *,
        policy_name: str | None = None,
        policy_id: str | None = None,
        reason: str = "",
        rewritten_content: Any | None = None,
        metadata: dict[str, Any] | None = None,
        risk: RiskLevel | str = RiskLevel.MEDIUM,
    ) -> "Decision":
        return cls(
            DecisionType.FILTER,
            policy_name=policy_name or policy_id,
            reason=reason,
            rewritten_content=rewritten_content,
            metadata=metadata,
            risk=risk,
        )

    def outranks(self, other: "Decision") -> bool:
        return self.severity > other.severity

    @property
    def is_terminal(self) -> bool:
        return self.decision in {DecisionType.BLOCK, DecisionType.REQUIRE_HUMAN}

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reason": self.reason,
            "policy_name": self.policy_name,
            "severity": self.severity,
            "rewritten_content": self.rewritten_content,
            "metadata": self.metadata,
            "risk": self.risk.value,
        }
