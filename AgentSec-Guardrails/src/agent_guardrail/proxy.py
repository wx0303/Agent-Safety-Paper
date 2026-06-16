from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .decisions import Decision, DecisionType
from .engine import GuardrailEngine, GuardrailResult
from .events import AgentEvent, RailType


class GuardrailViolation(RuntimeError):
    def __init__(self, result: GuardrailResult) -> None:
        super().__init__(result.decision.reason)
        self.result = result


@dataclass
class GuardrailProxy:
    """Convenience facade for the five-layer AgentSec pipeline."""

    engine: GuardrailEngine
    framework: str = "generic"

    def inspect(self, event: AgentEvent) -> GuardrailResult:
        return self.engine.evaluate_result(event)

    def guard_input(self, text: str, **metadata: Any) -> Decision:
        return self.engine.evaluate(
            AgentEvent.from_text(text, RailType.INPUT, framework=self.framework, **metadata)
        )

    def guard_plan(self, plan_step: str, user_goal: str, **metadata: Any) -> Decision:
        return self.engine.evaluate(
            AgentEvent(
                rail=RailType.PLANNER,
                content=plan_step,
                framework=self.framework,
                metadata={"user_goal": user_goal, "plan_step": plan_step, **metadata},
            )
        )

    def guard_retrieval(self, docs: list[dict[str, Any]], **metadata: Any) -> Decision:
        return self.engine.evaluate(
            AgentEvent.from_retrieval(docs, framework=self.framework, **metadata)
        )

    def guard_memory_write(
        self,
        key: str,
        value: Any,
        scope: str,
        **metadata: Any,
    ) -> Decision:
        return self.engine.evaluate(
            AgentEvent.from_memory_write(
                key,
                value,
                scope=scope,
                framework=self.framework,
                **metadata,
            )
        )

    def guard_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_fn: Callable[[dict[str, Any]], Any] | None = None,
        **metadata: Any,
    ) -> Any | Decision:
        request = AgentEvent.from_tool_call(
            tool_name,
            tool_args,
            framework=self.framework,
            **metadata,
        )
        request_result = self.inspect(request)
        if request_result.decision.decision in {
            DecisionType.BLOCK,
            DecisionType.REQUIRE_HUMAN,
        }:
            return request_result.decision

        if tool_fn is None:
            return request_result.decision

        safe_args = request_result.event.content
        output = tool_fn(safe_args)
        result_decision = self.guard_tool_result(tool_name, output, **metadata)
        if result_decision.decision in {DecisionType.FILTER, DecisionType.REWRITE}:
            return result_decision.rewritten_content
        if result_decision.decision != DecisionType.ALLOW:
            return result_decision
        return output

    def run_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        call: Callable[[dict[str, Any]], Any],
        **metadata: Any,
    ) -> Any:
        result = self.guard_tool_call(tool_name, arguments, call, **metadata)
        if isinstance(result, Decision):
            raise GuardrailViolation(
                GuardrailResult(
                    event=AgentEvent.from_tool_call(
                        tool_name,
                        arguments,
                        framework=self.framework,
                        **metadata,
                    ),
                    decision=result,
                    decisions=[result],
                )
            )
        return result

    def guard_tool_result(self, tool_name: str, tool_result: Any, **metadata: Any) -> Decision:
        return self.engine.evaluate(
            AgentEvent.from_tool_result(
                tool_name,
                tool_result,
                framework=self.framework,
                **metadata,
            )
        )

    def guard_output(self, text: str, **metadata: Any) -> Decision:
        return self.engine.evaluate(
            AgentEvent.from_text(text, RailType.OUTPUT, framework=self.framework, **metadata)
        )

    # Backward-compatible helpers from the original prototype.
    def guard_text(self, text: str, rail: RailType, **metadata: Any) -> str:
        result = self.inspect(
            AgentEvent.from_text(text, rail, framework=self.framework, **metadata)
        )
        if result.decision.decision in {DecisionType.BLOCK, DecisionType.REQUIRE_HUMAN}:
            raise GuardrailViolation(result)
        return str(result.event.content)
