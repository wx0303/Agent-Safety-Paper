from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from agent_guardrail import AgentDojoCase, AgentDojoEvalResult, AgentRunResult, AgentTraceStep
from agent_guardrail.decisions import Decision
from agent_guardrail.engine import GuardrailResult
from agent_guardrail.events import AgentEvent

from .demo_catalog import DemoCase


ACTION_MEANINGS = {
    "allow": "放行：事件可以继续进入下一步 Agent runtime。",
    "filter": "过滤：中等风险内容已自动脱敏、移除或收窄后继续。",
    "block": "阻断：风险较高，停止传递给后续模型、工具或输出链路。",
    "rewrite": "改写：检测到敏感内容，脱敏/改写后再继续。",
    "degrade": "降级：内容可信度不足，只能低信任使用或触发保守路径。",
    "require_human": "人工确认：动作可能合理但风险高，需要人工审批后继续。",
}


def serialize_demo_case(demo_case: DemoCase) -> dict[str, Any]:
    return {
        "id": demo_case.id,
        "group": demo_case.group,
        "title": demo_case.title,
        "description": demo_case.description,
        "userInput": demo_case.spec.user_input,
        "metadata": {
            "runtime": "GuardedAgentRuntime",
            "llm": "StaticLLMClient by default; LocalTransformersLLM for CLI",
            "rails": ["input", "planner", "retrieval", "execution", "memory", "output"],
        },
    }


def serialize_run_result(demo_case: DemoCase, result: AgentRunResult) -> dict[str, Any]:
    final_action = result.final_decision.decision.value
    return {
        **serialize_demo_case(demo_case),
        "final": {
            "action": final_action,
            "policy": result.final_decision.policy_name or "engine_default",
            "risk": result.final_decision.risk.value,
            "severity": result.final_decision.severity,
            "reason": result.final_decision.reason or "All matched policies returned allow.",
            "meaning": ACTION_MEANINGS[final_action],
            "output": result.final_output
            or f"Stopped at {result.stopped_at}. {result.final_decision.reason}",
        },
        "plan": result.plan,
        "stoppedAt": result.stopped_at,
        "steps": [serialize_trace_step(step, index) for index, step in enumerate(result.trace)],
    }


def serialize_trace_step(step: AgentTraceStep, index: int) -> dict[str, Any]:
    if step.guardrail_result is not None:
        return serialize_guardrail_step(step, index)
    return {
        "kind": "llm" if step.kind == "llm" else "runtime",
        "title": step.name,
        "description": describe_step(step),
        "input": to_jsonable(step.input),
        "result": to_jsonable(step.output),
        "decision": "allow",
        "policies": [],
    }


def serialize_guardrail_step(step: AgentTraceStep, index: int) -> dict[str, Any]:
    result = step.guardrail_result
    assert result is not None
    return {
        "kind": "guard",
        "title": step.name,
        "description": describe_guardrail_result(result),
        "input": to_jsonable(result.event.content),
        "result": result.decision.reason or "ok",
        "decision": result.decision.decision.value,
        "policies": [serialize_decision(decision) for decision in result.decisions],
        "metadata": {
            "index": index,
            "rail": result.event.rail.value,
            "tool": result.event.tool_name,
            "target": result.event.target,
        },
    }


def serialize_decision(decision: Decision) -> dict[str, Any]:
    return {
        "name": decision.policy_name or "engine_default",
        "decision": decision.decision.value,
        "risk": decision.risk.value,
        "severity": decision.severity,
        "reason": decision.reason or "ok",
        "metadata": to_jsonable(decision.metadata),
        "rewrite": to_jsonable(decision.rewritten_content),
    }


def describe_step(step: AgentTraceStep) -> str:
    if step.kind == "llm":
        return "LLM adapter call."
    return "Runtime adapter action."


def describe_guardrail_result(result: GuardrailResult) -> str:
    rail = result.event.rail.value
    decision = result.decision.decision.value
    return f"{rail} rail returned {decision}."


def to_jsonable(value: Any) -> Any:
    if isinstance(value, AgentEvent):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    return value


def serialize_agentdojo_case(case: AgentDojoCase) -> dict[str, Any]:
    return {
        "id": case.case_id,
        "suite": case.suite,
        "userTask": case.user_task,
        "injectionTask": case.injection_task,
        "title": humanize_agentdojo_case_id(case.case_id),
        "description": case.notes,
        "userInput": case.spec.user_input,
        "expectedDecision": case.expected_decision,
        "expectedGuard": case.expected_guard,
        "metadata": {
            "benchmark": "agentdojo",
            "suite": case.suite,
            "user_task": case.user_task,
            "injection_task": case.injection_task,
        },
    }


def serialize_agentdojo_eval_result(eval_result: AgentDojoEvalResult) -> dict[str, Any]:
    final_decision = eval_result.result.final_decision
    final_action = final_decision.decision.value
    payload = serialize_agentdojo_case(eval_result.case)
    payload.update(
        {
            "final": {
                "action": final_action,
                "policy": final_decision.policy_name or "engine_default",
                "risk": final_decision.risk.value,
                "severity": final_decision.severity,
                "reason": final_decision.reason or "All matched policies returned allow.",
                "meaning": ACTION_MEANINGS[final_action],
                "output": eval_result.result.final_output
                or f"Stopped at {eval_result.result.stopped_at}. {final_decision.reason}",
            },
            "finalDecision": final_action,
            "stoppedAt": eval_result.result.stopped_at,
            "allowed": eval_result.result.allowed,
            "guardDecisions": [dict(item) for item in eval_result.guard_decisions],
            "steps": [serialize_trace_step(step, index) for index, step in enumerate(eval_result.result.trace)],
        }
    )
    return payload


def summarize_agentdojo_results(results: list[AgentDojoEvalResult]) -> dict[str, Any]:
    final_counts: dict[str, int] = {}
    guard_counts: dict[str, int] = {}
    suite_counts: dict[str, int] = {}
    stage_counts: dict[str, int] = {}

    for eval_result in results:
        final_action = eval_result.result.final_decision.decision.value
        final_counts[final_action] = final_counts.get(final_action, 0) + 1
        suite_counts[eval_result.case.suite] = suite_counts.get(eval_result.case.suite, 0) + 1
        for item in eval_result.guard_decisions:
            decision = item["decision"]
            guard_counts[decision] = guard_counts.get(decision, 0) + 1
            stage = item["stage"].split(":", maxsplit=1)[0]
            stage_counts[stage] = stage_counts.get(stage, 0) + 1

    actionable = sum(
        guard_counts.get(action, 0)
        for action in ("filter", "require_human", "block")
    )
    return {
        "total": len(results),
        "finalActions": final_counts,
        "guardActions": guard_counts,
        "suiteCounts": suite_counts,
        "stageCounts": stage_counts,
        "actionableGuardDecisions": actionable,
    }


def humanize_agentdojo_case_id(case_id: str) -> str:
    words = [word for word in case_id.replace("-", "_").split("_") if word]
    acronyms = {"rag", "api", "llm"}
    return " ".join(word.upper() if word in acronyms else word.capitalize() for word in words)
