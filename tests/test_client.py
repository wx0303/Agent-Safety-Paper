"""GuardrailClient plumbing: event construction, tool-call flow, fail modes.

A scripted FakeTransport stands in for the remote PDP; we assert the SDK ships
the right event and acts correctly on the returned Decision.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentsec_sdk import (
    Decision,
    DecisionType,
    GuardrailClient,
    GuardrailConfig,
    GuardrailContext,
    GuardrailUnavailable,
    GuardrailViolation,
    Transport,
)
from support import FakeTransport, allow, block, is_tool_result, require_human, rewrite


def make_client(responder, **context_kw) -> GuardrailClient:
    transport = FakeTransport(responder)
    ctx = GuardrailContext(**context_kw) if context_kw else None
    return GuardrailClient(transport, context=ctx)


# ------------------------------------------------------------------ basic rails


def test_guard_input_plumbs_decision_through():
    client = make_client(block("nope"))
    decision = client.guard_input("hello")
    assert decision.decision == DecisionType.BLOCK
    assert decision.reason == "nope"


def test_context_is_injected_into_every_event():
    transport = FakeTransport(allow())
    client = GuardrailClient(
        transport, context=GuardrailContext(session_id="s1", trace_id="t1", framework="fw")
    )
    client.guard_input("hello", source="ui", phase="request")
    event = transport.events[-1]
    assert event["session_id"] == "s1"
    assert event["trace_id"] == "t1"
    assert event["framework"] == "fw"
    assert event["rail"] == "input"
    assert event["source"] == "ui"  # recognized correlation field -> top level
    assert event["metadata"]["phase"] == "request"  # unknown kwarg -> metadata


# ----------------------------------------------------------------- tool-call flow


def test_tool_call_runs_fn_only_when_allowed():
    client = make_client(allow())
    ran: list[dict[str, Any]] = []

    def fn(args: dict[str, Any]) -> str:
        ran.append(args)
        return "result"

    out = client.guard_tool_call("calculator", {"x": 1}, fn)
    assert out == "result"
    assert ran == [{"x": 1}]


def test_tool_call_blocked_returns_decision_without_running_fn():
    client = make_client(require_human("hold"))
    ran = {"called": False}

    def fn(_a):
        ran["called"] = True
        return "should not run"

    result = client.guard_tool_call("send_email", {"to": "x@y.z"}, fn)
    assert isinstance(result, Decision)
    assert result.decision == DecisionType.REQUIRE_HUMAN
    assert ran["called"] is False


def test_tool_call_without_fn_returns_decision():
    client = make_client(allow())
    result = client.guard_tool_call("calculator", {"x": 1})
    assert isinstance(result, Decision)
    assert result.decision == DecisionType.ALLOW


def test_tool_call_rewrites_args_before_running_fn():
    # PDP rewrites the call args; the fn must receive the sanitized version.
    def responder(event):
        if is_tool_result(event):
            return allow()
        return rewrite({"to": "safe@corp.com"})

    client = make_client(responder)
    seen: list[dict[str, Any]] = []
    out = client.guard_tool_call("send_email", {"to": "evil@x"}, lambda a: seen.append(a) or "sent")
    assert seen == [{"to": "safe@corp.com"}]
    assert out == "sent"


def test_tool_call_result_block_returns_result_decision():
    # call allowed, but the PDP blocks the *result* (e.g. it leaked a secret).
    def responder(event):
        return block("leaked secret") if is_tool_result(event) else allow()

    client = make_client(responder)
    result = client.guard_tool_call("search", {"q": "x"}, lambda a: "api_key=abc")
    assert isinstance(result, Decision)
    assert result.decision == DecisionType.BLOCK


# ------------------------------------------------------------ raising-style helpers


def test_run_tool_call_raises_on_denied():
    client = make_client(block())
    with pytest.raises(GuardrailViolation):
        client.run_tool_call("calculator", {"x": 1}, lambda a: 2)


def test_guard_text_returns_rewritten_content():
    from agentsec_sdk import RailType

    client = make_client(rewrite("[CLEAN]"))
    assert client.guard_text("dirty", RailType.OUTPUT) == "[CLEAN]"


# ----------------------------------------------------------------- required fields


def test_missing_required_fields_raise_locally_without_a_request():
    transport = FakeTransport(allow())
    client = GuardrailClient(transport)
    with pytest.raises(ValueError):
        client.guard_plan("do a thing", user_goal="")
    with pytest.raises(ValueError):
        client.guard_memory_write("k", "v", "")
    assert transport.events == []  # validated before any network call


# ----------------------------------------------------------------- error / fail mode


class _FailingTransport(Transport):
    def evaluate(self, event):  # noqa: ANN001
        raise GuardrailUnavailable("connection refused")


def test_fail_closed_synthesizes_block():
    client = GuardrailClient(_FailingTransport(), config=GuardrailConfig(fail_mode="closed"))
    decision = client.guard_input("hello")
    assert decision.decision == DecisionType.BLOCK
    assert decision.policy_name == "sdk.transport"
    assert decision.metadata.get("transport_error") is True


def test_fail_closed_blocks_tool_execution_without_running_fn():
    client = GuardrailClient(_FailingTransport(), config=GuardrailConfig(fail_mode="closed"))
    ran = {"called": False}

    def fn(_a):
        ran["called"] = True
        return "should not run"

    result = client.guard_tool_call("calculator", {"x": 1}, fn)
    assert isinstance(result, Decision)
    assert result.decision == DecisionType.BLOCK
    assert ran["called"] is False


def test_fail_open_allows():
    client = GuardrailClient(_FailingTransport(), config=GuardrailConfig(fail_mode="open"))
    decision = client.guard_input("hello")
    assert decision.decision == DecisionType.ALLOW
    assert decision.metadata.get("transport_error") is True
