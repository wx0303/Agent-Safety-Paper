from agent_guardrail import (
    AgentEvent,
    Decision,
    DecisionType,
    GuardrailEngine,
    Policy,
    RailType,
)


class RewritePolicy(Policy):
    policy_id = "rewrite"
    rail_types = {RailType.INPUT}

    def evaluate(self, event: AgentEvent) -> Decision:
        return Decision(
            DecisionType.REWRITE,
            policy_id=self.policy_id,
            rewritten_content=str(event.content).replace("secret", "redacted"),
        )


class FilterPolicy(Policy):
    policy_id = "filter"
    rail_types = {RailType.INPUT}

    def evaluate(self, event: AgentEvent) -> Decision:
        return Decision.filter(
            policy_id=self.policy_id,
            rewritten_content=str(event.content).replace("token", "filtered"),
            reason="filtered",
        )


class DegradePolicy(Policy):
    policy_id = "degrade"
    rail_types = {RailType.INPUT}

    def evaluate(self, event: AgentEvent) -> Decision:
        return Decision(DecisionType.DEGRADE, policy_id=self.policy_id, reason="lower trust")


class BlockPolicy(Policy):
    policy_id = "block"
    rail_types = {RailType.OUTPUT}

    def evaluate(self, event: AgentEvent) -> Decision:
        return Decision(DecisionType.BLOCK, policy_id=self.policy_id, reason="blocked")


def test_engine_selects_most_severe_decision() -> None:
    engine = GuardrailEngine([RewritePolicy(), DegradePolicy()])
    result = engine.evaluate_result(AgentEvent.from_text("secret input"))
    assert result.decision.decision == DecisionType.DEGRADE
    assert result.event.content == "redacted input"


def test_engine_preserves_rewritten_content_when_rewrite_is_final() -> None:
    engine = GuardrailEngine([RewritePolicy()])
    decision = engine.evaluate(AgentEvent.from_text("secret input"))
    assert decision.decision == DecisionType.REWRITE
    assert decision.rewritten_content == "redacted input"


def test_engine_preserves_filtered_content_when_filter_is_final() -> None:
    engine = GuardrailEngine([FilterPolicy()])
    decision = engine.evaluate(AgentEvent.from_text("token input"))
    assert decision.decision == DecisionType.FILTER
    assert decision.rewritten_content == "filtered input"


def test_engine_filters_policies_by_rail() -> None:
    engine = GuardrailEngine([BlockPolicy()])
    decision = engine.evaluate(AgentEvent.from_text("safe input", RailType.INPUT))
    assert decision.decision == DecisionType.ALLOW


def test_engine_evaluate_many_returns_decisions() -> None:
    engine = GuardrailEngine([BlockPolicy()])
    decisions = engine.evaluate_many(
        [
            AgentEvent.from_text("safe input", RailType.INPUT),
            AgentEvent.from_text("unsafe output", RailType.OUTPUT),
        ]
    )
    assert [decision.decision for decision in decisions] == [
        DecisionType.ALLOW,
        DecisionType.BLOCK,
    ]
