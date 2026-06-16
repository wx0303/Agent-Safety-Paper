from agent_guardrail import (
    AgentEvent,
    Decision,
    DecisionType,
    GuardrailEngine,
    GuardrailProxy,
    ToolPermissionPolicy,
    ToolResultInspectionPolicy,
)


def make_engine() -> GuardrailEngine:
    return GuardrailEngine(
        [
            ToolPermissionPolicy(
                allowed_tools=["calculator", "search", "read_file"],
                high_risk_tools=["send_email", "delete_file", "write_file", "transfer_money", "shell_exec"],
            ),
            ToolResultInspectionPolicy(),
        ]
    )


def test_unauthorized_tool_call_requires_human() -> None:
    decision = make_engine().evaluate(AgentEvent.from_tool_call("unknown_tool", {}))
    assert decision.decision == DecisionType.REQUIRE_HUMAN


def test_high_risk_tool_requires_human() -> None:
    decision = make_engine().evaluate(AgentEvent.from_tool_call("send_email", {"body": "hi"}))
    assert decision.decision == DecisionType.REQUIRE_HUMAN


def test_tool_args_with_sensitive_field_are_filtered() -> None:
    result = make_engine().evaluate_result(
        AgentEvent.from_tool_call("search", {"query": "x", "token": "abc1234567890xyz"})
    )
    assert result.decision.decision == DecisionType.FILTER
    assert result.event.content["token"] == "[REDACTED_SECRET]"


def test_tool_result_token_is_filtered() -> None:
    result = make_engine().evaluate_result(
        AgentEvent.from_tool_result("search", "token=abc1234567890xyz")
    )
    assert result.decision.decision == DecisionType.FILTER
    assert result.event.content == "[REDACTED_SECRET]"


def test_proxy_executes_allowed_tool() -> None:
    proxy = GuardrailProxy(make_engine())

    def add(args: dict[str, int]) -> int:
        return args["left"] + args["right"]

    result = proxy.guard_tool_call("calculator", {"left": 1, "right": 2}, add)
    assert result == 3


def test_proxy_returns_decision_for_unapproved_tool() -> None:
    proxy = GuardrailProxy(make_engine())
    result = proxy.guard_tool_call("unknown_tool", {})
    assert isinstance(result, Decision)
    assert result.decision == DecisionType.REQUIRE_HUMAN


def test_proxy_returns_filtered_tool_output() -> None:
    proxy = GuardrailProxy(make_engine())

    def search(_args: dict[str, str]) -> str:
        return "token=abc1234567890xyz"

    result = proxy.guard_tool_call("search", {"query": "debug"}, search)
    assert result == "[REDACTED_SECRET]"
