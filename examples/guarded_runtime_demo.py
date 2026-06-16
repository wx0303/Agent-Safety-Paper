from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DEFAULT_MODEL_PATH = ROOT.parent / "ckpts" / "Meta-Llama-3.1-8B-Instruct"

from agent_guardrail import (  # noqa: E402
    AgentRunResult,
    AgentTraceStep,
    GuardedAgentRuntime,
    LocalTransformersLLM,
    ToolRegistry,
    build_default_guardrail_proxy,
)
from agent_guardrail.decisions import Decision  # noqa: E402
from agent_guardrail.engine import GuardrailResult  # noqa: E402
from agent_guardrail.events import AgentEvent  # noqa: E402
from apps.api.demo_catalog import list_demo_cases  # noqa: E402
from apps.api.tool_registry import build_demo_tool_registry  # noqa: E402


ACTION_EXPLANATIONS = {
    "allow": "放行：事件可以继续进入下一步 Agent runtime。",
    "filter": "过滤：中等风险内容已自动脱敏、移除或收窄后继续。",
    "block": "阻断：风险较高，停止传递给后续模型、工具或输出链路。",
    "rewrite": "改写：检测到敏感内容，脱敏/改写后再继续。",
    "degrade": "降级：内容可信度不足，只能低信任使用或触发保守路径。",
    "require_human": "人工确认：动作可能合理但风险高，需要人工审批后继续。",
}


def build_tools() -> ToolRegistry:
    return build_demo_tool_registry()


def build_runtime(args: argparse.Namespace) -> GuardedAgentRuntime:
    log_path = ROOT / "logs" / "guarded_runtime_demo.jsonl"
    if log_path.exists():
        log_path.unlink()

    proxy = build_default_guardrail_proxy(
        framework="guarded-runtime-demo",
        audit_log_path=str(log_path),
    )
    llm = LocalTransformersLLM(
        args.model_path,
        model_name="Meta-Llama-3.1-8B-Instruct",
        max_new_tokens=args.max_new_tokens,
        device_map=args.device_map,
        cuda_visible_devices=args.cuda_visible_devices,
        skip_model=args.skip_model,
    )
    return GuardedAgentRuntime(proxy=proxy, llm=llm, tools=build_tools())


def print_architecture(args: argparse.Namespace) -> None:
    print_section("0. Reusable runtime integration")
    print("guarded_runtime_demo.py is now a thin CLI over package modules:")
    print("  agent_guardrail.runtime.GuardedAgentRuntime")
    print("  agent_guardrail.runtime.LocalTransformersLLM")
    print("  agent_guardrail.runtime.ToolRegistry")
    print("  agent_guardrail.policy_presets.build_default_guardrail_proxy")
    print()
    print("User input -> Input Guard -> LLM planner -> Planner Guard")
    print("  -> Runtime retrieval/tool/memory adapters -> corresponding Guards")
    print("  -> Final LLM answer -> Output & Audit Guard -> User")

    print_section("0.1 LLM adapter")
    print(f"Model path: {args.model_path}")
    print("Model name: Meta-Llama-3.1-8B-Instruct")
    print(f"Max new tokens: {args.max_new_tokens}")
    print(f"CUDA_VISIBLE_DEVICES: {args.cuda_visible_devices or os.environ.get('CUDA_VISIBLE_DEVICES', 'not set')}")
    if args.skip_model:
        print("Mode: skip model loading; runtime uses fallback text.")
    else:
        print("Mode: local Transformers adapter will call the model when rails allow it.")


def print_run_result(name: str, result: AgentRunResult) -> None:
    print_section(f"Scenario: {name}")
    print_block("User input", result.user_input)
    for step in result.trace:
        print_trace_step(step)
    print_subtitle("Scenario result")
    action = result.final_decision.decision.value
    print(f"action    : {action}")
    print(f"policy    : {result.final_decision.policy_name or 'engine_default'}")
    print(f"risk      : {result.final_decision.risk.value}, severity={result.final_decision.severity}")
    print(f"reason    : {result.final_decision.reason or 'All matched policies returned allow.'}")
    print(f"meaning   : {ACTION_EXPLANATIONS[action]}")
    print(f"stopped at: {result.stopped_at or 'not stopped'}")
    if result.plan is not None:
        print_block("Approved/checked plan", result.plan)
    if result.final_output is not None:
        print_block("User-visible output", result.final_output)


def print_trace_step(step: AgentTraceStep) -> None:
    print_subtitle(step.name)
    if step.kind == "guardrail" and step.guardrail_result is not None:
        print_guardrail_step(step.input, step.guardrail_result)
        return
    if step.kind == "llm":
        source = step.metadata.get("source")
        if source == "override":
            print("LLM adapter: deterministic override for reproducible safety scenario.")
        else:
            model = step.llm_response.model if step.llm_response else "unknown"
            print(f"LLM adapter: {model}")
        print_block("LLM input", step.input)
        print_block("LLM output", step.output)
        return
    print_block("Runtime input", step.input)
    print_block("Runtime output", step.output)


def print_guardrail_step(event: AgentEvent, result: GuardrailResult) -> None:
    print(f"Rail: {event.rail.value}")
    if event.tool_name:
        print(f"Tool: {event.tool_name}")
    if event.target:
        print(f"Target: {event.target}")
    if event.metadata:
        print_block("Metadata", event.metadata)
    print_block("Input/Event Content", event.content)
    print_policy_trace(result.decisions)
    print_final_decision(result.decision, result.event.content)


def print_policy_trace(decisions: list[Decision]) -> None:
    print("Policy execution trace:")
    if not decisions:
        print("  No matching policy was executed.")
        return
    for index, decision in enumerate(decisions, start=1):
        print(f"  [{index}] {decision.policy_name or 'unknown_policy'}")
        print(f"      decision : {decision.decision.value}")
        print(f"      risk     : {decision.risk.value}, severity={decision.severity}")
        print(f"      reason   : {decision.reason or 'ok'}")
        if decision.metadata:
            print(f"      metadata : {dump(decision.metadata)}")
        if decision.rewritten_content is not None:
            print(f"      filtered : {dump(decision.rewritten_content)}")


def print_final_decision(decision: Decision, event_content: Any) -> None:
    action = decision.decision.value
    print("Final result:")
    print(f"  action  : {action}")
    print(f"  policy  : {decision.policy_name or 'engine_default'}")
    print(f"  risk    : {decision.risk.value}, severity={decision.severity}")
    print(f"  reason  : {decision.reason or 'All matched policies returned allow.'}")
    print(f"  meaning : {ACTION_EXPLANATIONS[action]}")
    if decision.rewritten_content is not None:
        print_block("  content returned to runtime", event_content)


def print_section(title: str) -> None:
    print(f"\n{'=' * 88}")
    print(title)
    print("=" * 88)


def print_subtitle(title: str) -> None:
    print(f"\n--- {title} ---")


def print_block(label: str, value: Any) -> None:
    print(f"{label}:")
    for line in dump(value).splitlines():
        print(f"  {line}")


def dump(value: Any) -> str:
    serializable = serialize(value)
    if isinstance(serializable, str):
        return serializable
    try:
        return json.dumps(serializable, ensure_ascii=False, indent=2, sort_keys=True)
    except TypeError:
        return str(serializable)


def serialize(value: Any) -> Any:
    if isinstance(value, AgentEvent):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "AgentSec Guardrails runtime integration demo with optional local "
            "Meta-Llama-3.1-8B-Instruct inference."
        )
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=DEFAULT_MODEL_PATH,
        help="Path to local Meta-Llama-3.1-8B-Instruct checkpoint.",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=160,
        help="Maximum new tokens for the local model response.",
    )
    parser.add_argument(
        "--device-map",
        default="auto",
        help="Transformers device_map value for local model loading.",
    )
    parser.add_argument(
        "--cuda-visible-devices",
        default="1",
        help="CUDA_VISIBLE_DEVICES value used before loading the local model.",
    )
    parser.add_argument(
        "--skip-model",
        action="store_true",
        help="Run guardrail logic without loading or calling the local model.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime = build_runtime(args)
    print_architecture(args)
    for scenario in list_demo_cases():
        result = runtime.run(scenario.spec)
        print_run_result(scenario.title, result)

    print_section("Audit log")
    print(f"Audit log written to: {ROOT / 'logs' / 'guarded_runtime_demo.jsonl'}")
    print("The JSONL records come from AuditLoggingPolicy inside the default policy preset.")


if __name__ == "__main__":
    main()
