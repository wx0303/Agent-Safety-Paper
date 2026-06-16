from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from .decisions import Decision, DecisionType
from .events import AgentEvent
from .policies import Policy


class AuditHook(Protocol):
    def __call__(self, event: AgentEvent, decision: Decision) -> None:
        ...


@dataclass
class GuardrailResult:
    event: AgentEvent
    decision: Decision
    decisions: list[Decision] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.decision.decision in {
            DecisionType.ALLOW,
            DecisionType.FILTER,
            DecisionType.REWRITE,
            DecisionType.DEGRADE,
        }


class GuardrailEngine:
    """Runs matching policies for a normalized AgentEvent."""

    def __init__(
        self,
        policies: list[Policy] | None = None,
        audit_hooks: list[AuditHook] | None = None,
    ) -> None:
        self._policies = policies or []
        self._audit_hooks = audit_hooks or []

    @property
    def policies(self) -> tuple[Policy, ...]:
        return tuple(self._policies)

    @property
    def audit_hooks(self) -> tuple[AuditHook, ...]:
        return tuple(self._audit_hooks)

    def add_policy(self, policy: Policy) -> None:
        self._policies.append(policy)

    def add_audit_hook(self, hook: AuditHook) -> None:
        self._audit_hooks.append(hook)

    def evaluate(self, event: AgentEvent) -> Decision:
        """Evaluate an event and return the final decision.

        Use evaluate_result() when the caller also needs the rewritten event and
        the per-policy decision trace.
        """

        return self.evaluate_result(event).decision

    def evaluate_result(self, event: AgentEvent) -> GuardrailResult:
        current_event = event
        final_decision = Decision.allow()
        decisions: list[Decision] = []

        for policy in self._policies:
            if not policy.applies_to(current_event):
                continue

            decision = policy.evaluate(current_event)
            decisions.append(decision)
            self._audit(current_event, decision, stage="policy")

            if decision.decision in {DecisionType.FILTER, DecisionType.REWRITE}:
                current_event = current_event.with_content(decision.rewritten_content)

            if decision.outranks(final_decision) or (
                decision.decision in {DecisionType.FILTER, DecisionType.REWRITE}
                and final_decision.decision in {DecisionType.FILTER, DecisionType.REWRITE}
            ):
                final_decision = decision

            if decision.decision == DecisionType.BLOCK:
                break

        if final_decision.decision in {DecisionType.FILTER, DecisionType.REWRITE}:
            final_decision.rewritten_content = current_event.content

        self._audit(current_event, final_decision, stage="final")
        return GuardrailResult(event=current_event, decision=final_decision, decisions=decisions)

    # Original proxy code used inspect-style result semantics; keep an alias.
    def inspect(self, event: AgentEvent) -> GuardrailResult:
        return self.evaluate_result(event)

    def evaluate_many(self, events: list[AgentEvent]) -> list[Decision]:
        return [self.evaluate(event) for event in events]

    def _audit(self, event: AgentEvent, decision: Decision, *, stage: str) -> None:
        audited_decision = Decision(
            decision.decision,
            reason=decision.reason,
            policy_name=decision.policy_name,
            severity=decision.severity,
            rewritten_content=decision.rewritten_content,
            metadata={**decision.metadata, "stage": stage},
            risk=decision.risk,
        )
        for hook in self._audit_hooks:
            hook(event, audited_decision)

        for policy in self._policies:
            recorder: Callable[[AgentEvent, Decision], None] | None = getattr(
                policy, "record_decision", None
            )
            if recorder is not None:
                recorder(event, audited_decision)
