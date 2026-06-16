"""Test doubles: a scripted in-memory PDP and Decision builders.

The SDK is a pure PEP client — its job is to serialize events, ship them to a
decision point, and plumb the verdict back. So the tests stand in a *fake* PDP
(``FakeTransport``) that returns scripted decisions, and assert on the SDK's
plumbing (event construction, tool-call flow, fail modes), not on policy logic.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agentsec_sdk import Decision, DecisionType, RiskLevel
from agentsec_sdk.transport.base import Transport


class FakeTransport(Transport):
    """In-memory decision point. Records every event; returns scripted verdicts.

    ``responder`` is either a fixed ``Decision`` or a callable
    ``(event_dict) -> Decision`` so a test can return different verdicts for the
    tool-call vs the tool-result leg of ``guard_tool_call``.
    """

    def __init__(self, responder: Callable[[dict[str, Any]], Decision] | Decision) -> None:
        self._responder = responder
        self.events: list[dict[str, Any]] = []

    def evaluate(self, event: dict[str, Any]) -> dict[str, Any]:
        self.events.append(event)
        result = self._responder(event) if callable(self._responder) else self._responder
        return result.to_dict() if isinstance(result, Decision) else dict(result)


def allow(**kw: Any) -> Decision:
    return Decision(DecisionType.ALLOW, **kw)


def block(reason: str = "blocked") -> Decision:
    return Decision(DecisionType.BLOCK, reason=reason, risk=RiskLevel.HIGH)


def require_human(reason: str = "needs a human") -> Decision:
    return Decision(DecisionType.REQUIRE_HUMAN, reason=reason)


def rewrite(content: Any, reason: str = "rewritten") -> Decision:
    return Decision(DecisionType.REWRITE, rewritten_content=content, reason=reason)


def is_tool_result(event: dict[str, Any]) -> bool:
    """True for the tool-*result* leg (vs the tool-*call* leg) of an execution event."""

    return "tool_result" in event
