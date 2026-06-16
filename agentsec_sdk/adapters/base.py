from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..client import GuardrailClient, GuardrailOutcome
from ..errors import GuardrailViolation
from ..wire import Decision, DecisionType

_TERMINAL = {DecisionType.BLOCK, DecisionType.REQUIRE_HUMAN}


@dataclass
class Applied:
    """The resolved outcome of applying a Decision to a piece of content.

    ``proceed`` is False for terminal decisions (BLOCK / REQUIRE_HUMAN).
    ``content`` is the rewritten/degraded payload when a policy changed it, else
    the original.
    """

    proceed: bool
    content: Any
    decision: Decision


def apply_decision(decision: Decision, original: Any) -> Applied:
    """Reduce a Decision + original content to a proceed/content pair.

    The single place every adapter funnels Decisions through, so block/rewrite/
    degrade handling stays consistent across frameworks.
    """

    if decision.decision in _TERMINAL:
        return Applied(proceed=False, content=None, decision=decision)
    if decision.decision in {DecisionType.REWRITE, DecisionType.DEGRADE}:
        content = (
            decision.rewritten_content
            if decision.rewritten_content is not None
            else original
        )
        return Applied(proceed=True, content=content, decision=decision)
    return Applied(proceed=True, content=original, decision=decision)


class GuardrailAdapter:
    """Framework-neutral translation core every concrete adapter builds on.

    Wraps a :class:`GuardrailClient` and exposes one method per rail that
    returns the *resolved* (possibly rewritten) content and raises
    :class:`GuardrailViolation` on a terminal decision. A framework binding just
    calls these from its own hooks — it never touches policy logic.
    """

    def __init__(self, client: GuardrailClient) -> None:
        self.client = client

    # -- text rails -------------------------------------------------------

    def input(self, text: str, **metadata: Any) -> str:
        return self._resolve_text(self.client.guard_input(text, **metadata), text)

    def output(self, text: str, **metadata: Any) -> str:
        return self._resolve_text(self.client.guard_output(text, **metadata), text)

    def plan(self, plan_step: str, user_goal: str, **metadata: Any) -> str:
        decision = self.client.guard_plan(plan_step, user_goal, **metadata)
        return self._resolve_text(decision, plan_step)

    # -- structured rails -------------------------------------------------

    def retrieval(self, docs: list[dict[str, Any]], **metadata: Any) -> list[dict[str, Any]]:
        decision = self.client.guard_retrieval(docs, **metadata)
        applied = apply_decision(decision, docs)
        if not applied.proceed:
            raise GuardrailViolation(GuardrailOutcome(decision=decision))
        return applied.content

    def memory_write(self, key: str, value: Any, scope: str, **metadata: Any) -> Any:
        decision = self.client.guard_memory_write(key, value, scope, **metadata)
        applied = apply_decision(decision, value)
        if not applied.proceed:
            raise GuardrailViolation(GuardrailOutcome(decision=decision))
        return applied.content

    # -- tool rail (execution) -------------------------------------------

    def run_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_fn: Callable[[dict[str, Any]], Any],
        **metadata: Any,
    ) -> Any:
        """Guard + run a tool; raises ``GuardrailViolation`` if denied."""

        return self.client.run_tool_call(tool_name, tool_args, tool_fn, **metadata)

    def check_tool(
        self, tool_name: str, tool_args: dict[str, Any], **metadata: Any
    ) -> Decision:
        """Check a tool call without executing it (returns the Decision)."""

        return self.client.guard_tool_call(tool_name, tool_args, **metadata)

    def check_tool_result(self, tool_name: str, result: Any, **metadata: Any) -> Any:
        decision = self.client.guard_tool_result(tool_name, result, **metadata)
        applied = apply_decision(decision, result)
        if not applied.proceed:
            raise GuardrailViolation(GuardrailOutcome(decision=decision))
        return applied.content

    # -- internals --------------------------------------------------------

    def _resolve_text(self, decision: Decision, original: str) -> str:
        applied = apply_decision(decision, original)
        if not applied.proceed:
            raise GuardrailViolation(GuardrailOutcome(decision=decision))
        return str(applied.content)
