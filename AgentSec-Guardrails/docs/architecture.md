# Architecture

This project follows a NeMo Guardrails-like rail model, but it is designed as a framework-neutral agent safety proxy and guarded runtime integration.

## Core Pipeline

```text
LangChain / OpenClaw / Hermes / MCP Agent / custom runtime
        |
Framework adapter creates AgentRunSpec or AgentEvent
        |
GuardedAgentRuntime orchestrates the agent loop
        |
GuardrailProxy converts runtime boundaries to AgentEvent
        |
GuardrailEngine runs policy modules
        |
Decision: allow / filter / degrade / require_human / block
        |
Runtime continues, filters, degrades, pauses, or stops
```

## Enterprise Project Layout

```text
apps/
  api/                       FastAPI backend; owns HTTP routes and response serialization
  web/public/                Frontend static app; no Python runtime code
config/                      Policy and runtime configuration
docs/                        Architecture and policy documentation
examples/                    CLI examples and operator demos
src/agent_guardrail/         Reusable SDK package
tests/                       Unit and integration tests
```

The frontend never imports Python modules. It calls the backend over HTTP:

```text
GET  /api/demo/cases
POST /api/demo/cases/{case_id}/run
```

The backend owns application orchestration and depends on the reusable SDK in
`src/agent_guardrail`. The SDK does not depend on `apps/api` or `apps/web`.

## Runtime Integration

The reusable runtime integration lives under `src/agent_guardrail/runtime/`.

- `GuardedAgentRuntime`: orchestrates input checks, LLM planning, planner checks,
  retrieval checks, Tool Guard checks before and after tool execution, memory
  checks, final LLM answering, and Output Guard checks.
- `AgentRunSpec`: framework-neutral description of a user request plus runtime
  intents such as retrieval documents, tool requests, and memory writes.
- `LLMClient`: protocol for local, hosted, or test LLM adapters.
- `LocalTransformersLLM`: lazy local Hugging Face Transformers adapter.
- `StaticLLMClient`: deterministic adapter for tests and reproducible examples.
- `ToolExecutor`: protocol for tool adapters.
- `ToolRegistry`: simple callable-backed tool executor.

The LLM does not execute tools. The LLM proposes a plan; the runtime checks that
plan, then executes registered tools only after tool-call policies allow it.
Tool outputs are inspected by Tool Guard again before they become model context.
Output Guard is reserved for the final user-visible answer.

`examples/guarded_runtime_demo.py` is a thin CLI over these package modules. It is
not the owner of the runtime architecture.

## Rail Types

- `input`: user input, external messages, prompt injection before the agent sees them.
- `output`: final user-visible answer filtering, secret redaction, compliance and safety checks.
- `dialog`: multi-turn policy, role boundary protection, conversation state checks.
- `retrieval`: RAG query/result filtering, untrusted source scoring, retrieval poisoning detection.
- `execution`: tool calls, tool outputs, shell/API/browser/file access, least privilege enforcement.
- `memory`: memory and workspace writes, long-term memory poisoning, sensitive data persistence.
- `model`: model request/response inspection, model fallback, degradation, response rewriting.

NeMo Guardrails mainly exposes input, output, dialog, retrieval, and execution rails. This prototype keeps those categories and adds `memory` and `model` rails because autonomous agents often fail at workspace writes, persistent memory, and model/tool boundary crossings.

## Framework Adapters

Adapters should be thin. Their job is to translate framework-specific callbacks into `AgentEvent` objects or to fill an `AgentRunSpec` for `GuardedAgentRuntime`.

- LangChain: middleware around model calls, tool calls, tool results, and final output.
- OpenClaw: tool wrapper, plugin hook, gateway proxy, MCP proxy, or API proxy.
- Hermes: API proxy or runtime wrapper around model/tool execution.
- MCP Agent: MCP proxy that intercepts tool listing, tool invocation, and tool results.

The strategy is to avoid making the safety engine depend on any single framework. Each adapter can evolve separately while sharing the same rail and policy engine.

## Research Extension Points

New defense methods can be added as policy modules or rail modules:

- jailbreak defense classifier
- prompt injection detector
- indirect prompt injection scanner for retrieved documents
- tool risk scorer
- retrieval poisoning detector
- memory poisoning detector
- sensitive data detector
- human confirmation policy
- model degradation or fallback policy

Each method should implement the same interface. For detailed implementation guidance, see [Policy Interface](policy_interface.md).

```python
class Policy:
    policy_id: str
    rail_types: set[RailType]

    def evaluate(self, event: AgentEvent) -> Decision:
        ...
```

This keeps published research methods easy to plug in later. A defense method can return `filter`, `require_human`, or `block` without changing the agent framework integration; `rewrite` remains as a backward-compatible alias for older integrations.
