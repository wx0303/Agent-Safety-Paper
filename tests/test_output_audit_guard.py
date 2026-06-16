import json

from agent_guardrail import (
    AgentEvent,
    AuditLoggingPolicy,
    DecisionType,
    GuardrailEngine,
    OutputSafetyPolicy,
    RailType,
)


def test_output_secret_is_filtered() -> None:
    engine = GuardrailEngine([OutputSafetyPolicy()])
    result = engine.evaluate_result(
        AgentEvent.from_text("Here is secret=supersecret12345", RailType.OUTPUT)
    )
    assert result.decision.decision == DecisionType.FILTER
    assert result.event.content == "Here is [REDACTED_SECRET]"


def test_output_system_prompt_leak_is_blocked() -> None:
    engine = GuardrailEngine([OutputSafetyPolicy()])
    decision = engine.evaluate(
        AgentEvent.from_text("System prompt: do not disclose this.", RailType.OUTPUT)
    )
    assert decision.decision == DecisionType.BLOCK


def test_audit_log_writes_jsonl(tmp_path) -> None:
    log_path = tmp_path / "agent_guardrail.jsonl"
    audit = AuditLoggingPolicy(log_path=str(log_path))
    engine = GuardrailEngine([OutputSafetyPolicy(), audit])
    decision = engine.evaluate(
        AgentEvent.from_text("Safe final answer.", RailType.OUTPUT)
    )
    assert decision.decision == DecisionType.ALLOW
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert lines
    records = [json.loads(line) for line in lines]
    assert any(record["rail"] == "output" for record in records)
    assert any(record["decision"] == "allow" for record in records)
