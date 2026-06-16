from apps.api.demo_catalog import get_demo_case, list_demo_cases
from apps.api.main import create_runtime
from apps.api.serializers import serialize_run_result, summarize_agentdojo_results
from agent_guardrail import build_agentdojo_smoke_cases, run_agentdojo_cases


def test_demo_catalog_has_enterprise_api_cases() -> None:
    cases = list_demo_cases()
    assert len(cases) == 9
    assert get_demo_case("normal-agent-loop").title


def test_api_runtime_payload_redacts_tool_result_without_memory_write() -> None:
    demo_case = get_demo_case("tool-result-secret-loop")
    result = create_runtime().run(demo_case.spec)
    payload = serialize_run_result(demo_case, result)

    assert payload["id"] == "tool-result-secret-loop"
    assert payload["final"]["action"] == "allow"

    step_titles = {step["title"] for step in payload["steps"]}
    assert "tool_result:search" in step_titles
    assert not any(title.startswith("memory:") for title in step_titles)

    tool_result_step = next(step for step in payload["steps"] if step["title"] == "tool_result:search")
    assert tool_result_step["decision"] == "filter"
    assert "[REDACTED_SECRET]" in str(tool_result_step)
    assert "api_key=abc1234567890xyz" not in str(tool_result_step["input"])


def test_api_runtime_payload_exposes_promptarmor_input_case() -> None:
    demo_case = get_demo_case("promptarmor-input-sanitize-loop")
    result = create_runtime().run(demo_case.spec)
    payload = serialize_run_result(demo_case, result)

    assert payload["id"] == "promptarmor-input-sanitize-loop"
    assert payload["final"]["action"] == "allow"

    input_step = next(step for step in payload["steps"] if step["title"] == "input")
    assert input_step["decision"] == "filter"
    assert "promptarmor_sanitizer" in str(input_step)
    assert "Ignore previous instructions" not in str(input_step["result"])
    assert "reveal the system prompt" not in str(input_step["result"])


def test_api_runtime_payload_pauses_untrusted_memory_without_tool_call() -> None:
    demo_case = get_demo_case("memory-untrusted-long-term-loop")
    result = create_runtime().run(demo_case.spec)
    payload = serialize_run_result(demo_case, result)

    assert payload["id"] == "memory-untrusted-long-term-loop"
    assert payload["final"]["action"] == "allow"

    step_titles = {step["title"] for step in payload["steps"]}
    assert "memory:source_preference" in step_titles
    assert not any(title.startswith("tool_") for title in step_titles)

    memory_step = next(step for step in payload["steps"] if step["title"] == "memory:source_preference")
    assert memory_step["decision"] == "require_human"
    assert "Long-term memory write from untrusted_web requires human approval." in str(memory_step)
    assert "[REDACTED_SECRET]" not in str(payload["steps"])


def test_api_runtime_payload_exposes_melon_planner_guard_case() -> None:
    demo_case = get_demo_case("melon-planner-trace-loop")
    result = create_runtime().run(demo_case.spec)
    payload = serialize_run_result(demo_case, result)

    assert payload["id"] == "melon-planner-trace-loop"
    assert payload["final"]["action"] == "require_human"
    assert payload["stoppedAt"] == "planner"

    planner_step = next(step for step in payload["steps"] if step["title"] == "planner")
    assert planner_step["decision"] == "require_human"
    assert "MELON detected risky tool-call overlap" in str(planner_step)
    assert "melon_score" in str(planner_step)


def test_agentdojo_summary_counts_tiered_responses() -> None:
    results = run_agentdojo_cases(build_agentdojo_smoke_cases())
    summary = summarize_agentdojo_results(results)

    assert summary["total"] == 6
    assert summary["guardActions"]["filter"] >= 2
    assert summary["guardActions"]["require_human"] >= 2
    assert summary["guardActions"]["block"] >= 2
    assert summary["suiteCounts"]["workspace"] == 2
