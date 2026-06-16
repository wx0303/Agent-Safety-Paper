"""The vendored wire types must survive a to_dict -> from_dict round trip.

These are the contract the SDK speaks to ``agentsec-server``; if a field is
dropped here, a real request/response loses it on the wire.
"""

from __future__ import annotations

from agentsec_sdk import AgentEvent, Decision, DecisionType, RailType, RiskLevel


def test_event_round_trip_preserves_fields():
    event = AgentEvent.from_tool_call(
        "send_email",
        {"to": "a@b.com", "body": "hi"},
        framework="langchain",
        session_id="s1",
    )
    restored = AgentEvent.from_dict(event.to_dict())

    assert restored.rail == RailType.EXECUTION
    assert restored.tool_name == "send_email"
    assert restored.tool_args == {"to": "a@b.com", "body": "hi"}
    assert restored.framework == "langchain"
    assert restored.session_id == "s1"
    assert restored.event_id == event.event_id
    assert restored.timestamp == event.timestamp


def test_decision_round_trip_preserves_fields():
    decision = Decision(
        DecisionType.REWRITE,
        reason="redacted secret",
        policy_name="output.safety",
        rewritten_content="[REDACTED]",
        risk=RiskLevel.MEDIUM,
        metadata={"matched": ["secret"]},
    )
    restored = Decision.from_dict(decision.to_dict())

    assert restored.decision == DecisionType.REWRITE
    assert restored.reason == "redacted secret"
    assert restored.policy_name == "output.safety"
    assert restored.rewritten_content == "[REDACTED]"
    assert restored.risk == RiskLevel.MEDIUM
    assert restored.severity == decision.severity
    assert restored.metadata == {"matched": ["secret"]}


def test_enums_serialize_to_documented_lowercase_strings():
    # docs/sdk-config.md §7 pins these wire values; the server depends on them.
    assert RailType.EXECUTION.value == "execution"
    assert DecisionType.REQUIRE_HUMAN.value == "require_human"
    assert RiskLevel.HIGH.value == "high"
    event = AgentEvent.from_text("hi", RailType.INPUT)
    assert event.to_dict()["rail"] == "input"
    assert Decision(DecisionType.BLOCK).to_dict()["decision"] == "block"


def test_text_factory_routes_extras_to_metadata_and_correlation():
    event = AgentEvent.from_text(
        "hello", RailType.INPUT, framework="fw", trace_id="t1", phase="request"
    )
    assert event.trace_id == "t1"  # recognized correlation field -> dataclass field
    assert event.metadata == {"phase": "request"}  # unknown kwarg -> metadata
