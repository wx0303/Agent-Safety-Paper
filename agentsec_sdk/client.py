from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from .config import GuardrailConfig, GuardrailContext
from .errors import GuardrailViolation, TransportError
from .transport.base import Transport
from .wire import AgentEvent, Decision, DecisionType, RailType, RiskLevel

_TERMINAL = {DecisionType.BLOCK, DecisionType.REQUIRE_HUMAN}


@dataclass
class GuardrailOutcome:
    """Lightweight result wrapper attached to ``GuardrailViolation``."""

    decision: Decision
    event: AgentEvent | None = None


class GuardrailClient:
    """Thin PEP facade: build event -> transport.evaluate -> Decision.

    The ``guard_*`` surface is stable across transports, so swapping HTTP for
    gRPC (or pointing at a different server) needs no call-site changes. All
    policy evaluation happens on the remote server; this class only builds the
    event, ships it, and acts on the returned ``Decision``.
    """

    def __init__(
        self,
        transport: Transport,
        *,
        context: GuardrailContext | None = None,
        config: GuardrailConfig | None = None,
    ) -> None:
        self._transport = transport
        self._context = context or GuardrailContext()
        self._config = config or GuardrailConfig()

    # ------------------------------------------------------------------ rails

    def guard_input(self, text: str, **metadata: Any) -> Decision:
        return self._evaluate(self._text_event(text, RailType.INPUT, metadata))

    def guard_plan(self, plan_step: str, user_goal: str, **metadata: Any) -> Decision:
        if not user_goal:
            raise ValueError("guard_plan requires a non-empty user_goal")
        event = AgentEvent(
            rail=RailType.PLANNER,
            content=plan_step,
            framework=self._context.framework,
            metadata={"user_goal": user_goal, "plan_step": plan_step, **metadata},
        )
        return self._evaluate(self._apply_context(event))

    def guard_retrieval(self, docs: list[dict[str, Any]], **metadata: Any) -> Decision:
        if not isinstance(docs, list):
            raise ValueError("guard_retrieval requires a list of document dicts")
        event = AgentEvent.from_retrieval(
            docs, framework=self._context.framework, **metadata
        )
        return self._evaluate(self._apply_context(event))

    def guard_memory_write(
        self, key: str, value: Any, scope: str, **metadata: Any
    ) -> Decision:
        if not scope:
            raise ValueError("guard_memory_write requires a non-empty scope")
        event = AgentEvent.from_memory_write(
            key, value, scope=scope, framework=self._context.framework, **metadata
        )
        return self._evaluate(self._apply_context(event))

    def guard_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_fn: Callable[[dict[str, Any]], Any] | None = None,
        **metadata: Any,
    ) -> Any | Decision:
        """Guard a tool call; run ``tool_fn`` locally only when allowed.

        Returns the tool output on success, or a ``Decision`` when blocked,
        held for human review, or when ``tool_fn`` is omitted.
        """

        request = AgentEvent.from_tool_call(
            tool_name, tool_args, framework=self._context.framework, **metadata
        )
        decision = self._evaluate(self._apply_context(request))
        if decision.decision in _TERMINAL:
            return decision
        if tool_fn is None:
            return decision

        # "Decision remote, execution local": the callable never leaves this process.
        safe_args = (
            decision.rewritten_content
            if decision.rewritten_content is not None
            else tool_args
        )
        output = tool_fn(safe_args)
        result_decision = self.guard_tool_result(tool_name, output, **metadata)
        if result_decision.decision != DecisionType.ALLOW:
            return result_decision
        return output

    def guard_tool_result(self, tool_name: str, result: Any, **metadata: Any) -> Decision:
        event = AgentEvent.from_tool_result(
            tool_name, result, framework=self._context.framework, **metadata
        )
        return self._evaluate(self._apply_context(event))

    def guard_output(self, text: str, **metadata: Any) -> Decision:
        return self._evaluate(self._text_event(text, RailType.OUTPUT, metadata))

    # --------------------------------------------------------- raising helpers

    def run_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        call: Callable[[dict[str, Any]], Any],
        **metadata: Any,
    ) -> Any:
        """Like ``guard_tool_call`` but raises ``GuardrailViolation`` if denied."""

        result = self.guard_tool_call(tool_name, arguments, call, **metadata)
        if isinstance(result, Decision):
            raise GuardrailViolation(GuardrailOutcome(decision=result))
        return result

    def guard_text(self, text: str, rail: RailType, **metadata: Any) -> str:
        """Guard a text rail, raising on terminal decisions, else return text.

        Returns the rewritten text when a policy rewrote it.
        """

        event = self._text_event(text, rail, metadata)
        decision = self._evaluate(event)
        if decision.decision in _TERMINAL:
            raise GuardrailViolation(GuardrailOutcome(decision=decision, event=event))
        if decision.rewritten_content is not None:
            return str(decision.rewritten_content)
        return text

    # ----------------------------------------------------------------- internals

    def _text_event(
        self, text: str, rail: RailType, metadata: dict[str, Any]
    ) -> AgentEvent:
        event = AgentEvent.from_text(
            text, rail, framework=self._context.framework, **metadata
        )
        return self._apply_context(event)

    def _apply_context(self, event: AgentEvent) -> AgentEvent:
        ctx = self._context
        return replace(
            event,
            session_id=event.session_id or ctx.session_id,
            trace_id=event.trace_id or ctx.trace_id,
            parent_event_id=event.parent_event_id or ctx.parent_event_id,
            actor=event.actor or ctx.actor,
            source=event.source or ctx.source,
        )

    def _evaluate(self, event: AgentEvent) -> Decision:
        try:
            payload = self._transport.evaluate(event.to_dict())
        except TransportError as exc:
            return self._on_transport_error(exc)
        return Decision.from_dict(payload)

    def _on_transport_error(self, exc: TransportError) -> Decision:
        if self._config.fail_mode == "open":
            return Decision(
                DecisionType.ALLOW,
                policy_name="sdk.transport",
                reason=f"guardrail unavailable, fail-open: {exc}",
                metadata={"transport_error": True},
            )
        return Decision(
            DecisionType.BLOCK,
            policy_name="sdk.transport",
            reason=f"guardrail server unavailable: {exc}",
            risk=RiskLevel.HIGH,
            metadata={"transport_error": True},
        )
