from __future__ import annotations

from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is installed with api extras.
    load_dotenv = None

from agent_guardrail import (
    GuardedAgentRuntime,
    StaticLLMClient,
    build_agentdojo_smoke_cases,
    build_default_guardrail_proxy,
    run_agentdojo_cases,
)

from .demo_catalog import get_demo_case, list_demo_cases
from .serializers import (
    serialize_agentdojo_case,
    serialize_agentdojo_eval_result,
    serialize_demo_case,
    serialize_run_result,
    summarize_agentdojo_results,
)
from .tool_registry import build_demo_tool_registry

ROOT = Path(__file__).resolve().parents[2]

if load_dotenv is not None:
    load_dotenv(ROOT / ".env")


def create_runtime() -> GuardedAgentRuntime:
    proxy = build_default_guardrail_proxy(
        framework="agentsec-api",
        audit_log_path=str(ROOT / "logs" / "api_demo.jsonl"),
    )
    llm = StaticLLMClient(model_name="api-static-llm")
    return GuardedAgentRuntime(
        proxy=proxy,
        llm=llm,
        tools=build_demo_tool_registry(),
    )


try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
except ImportError as exc:  # pragma: no cover - exercised by import smoke tests.
    FastAPI = None  # type: ignore[assignment]
    HTTPException = None  # type: ignore[assignment]
    CORSMiddleware = None  # type: ignore[assignment]
    StaticFiles = None  # type: ignore[assignment]
    _FASTAPI_IMPORT_ERROR = exc
else:
    _FASTAPI_IMPORT_ERROR = None


if FastAPI is not None:
    WEB_ROOT = ROOT / "apps" / "web" / "public"
    app = FastAPI(title="AgentSec Guardrails API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/demo/cases")
    def demo_cases() -> dict[str, object]:
        return {"cases": [serialize_demo_case(case) for case in list_demo_cases()]}

    @app.post("/api/demo/cases/{case_id}/run")
    def run_demo_case(case_id: str) -> dict[str, object]:
        try:
            demo_case = get_demo_case(case_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown demo case: {case_id}") from exc

        runtime = create_runtime()
        result = runtime.run(demo_case.spec)
        return serialize_run_result(demo_case, result)

    @app.get("/api/agentdojo/cases")
    def agentdojo_cases() -> dict[str, object]:
        cases = build_agentdojo_smoke_cases()
        return {"cases": [serialize_agentdojo_case(case) for case in cases]}

    @app.post("/api/agentdojo/run")
    def run_agentdojo_benchmark() -> dict[str, object]:
        results = run_agentdojo_cases(build_agentdojo_smoke_cases())
        return {
            "summary": summarize_agentdojo_results(results),
            "results": [serialize_agentdojo_eval_result(result) for result in results],
        }

    app.mount("/", StaticFiles(directory=WEB_ROOT, html=True), name="web")
else:
    app = None


def require_app() -> object:
    if app is None:
        raise RuntimeError(
            "FastAPI is not installed. Install the API extras with "
            '`pip install -e ".[api]"` before running the backend.'
        ) from _FASTAPI_IMPORT_ERROR
    return app
