# AgentSec Guardrails Design

## Positioning

AgentSec Guardrails is a framework-neutral runtime security middleware for
autonomous agents. It normalizes events from LangChain, AutoGen, CrewAI, MCP
agents, OpenAI-style runtimes, or custom systems into one `AgentEvent` shape,
runs policy modules, and returns a unified `Decision`.

This repository is a research prototype. It demonstrates the control plane and
extension points, but it is not an industrial-grade security product.

## Five-Layer Pipeline

```text
User input
  -> Input Guard
  -> LLM planning
  -> Planner Guard
  -> Runtime retrieval / tool / memory adapters
  -> Retrieval/Memory/Tool Guards
  -> Final LLM answer
  -> Output & Audit Guard
  -> Final response / action
```

Rail mapping:

```text
Input Guard                -> INPUT
Planner Guard              -> PLANNER
Retrieval/Memory Guard     -> RETRIEVAL + MEMORY
Tool Execution Guard       -> EXECUTION
Output & Audit Guard       -> OUTPUT + AUDIT
```

`MODEL` and `DIALOG` remain optional extension rails for model inspection and
multi-turn role-boundary policies.

## Core Objects

`AgentEvent`

The normalized runtime event. It carries `rail`, `content`, framework metadata,
trace fields, tool fields, retrieval documents, memory fields, risk scores, and
timestamps.

`Policy`

The pluggable defense interface. A policy declares `rail_types` and implements
`evaluate(event) -> Decision`. Policies should not depend on LangChain, MCP, or
other framework internals.

`Decision`

The unified output of a policy:

```text
allow < filter/rewrite < degrade < require_human < block
```

`GuardrailEngine`

Runs only policies that match `event.rail`, applies filter/rewrite decisions in policy
order, selects the highest-severity final decision, and records audit traces.

`GuardrailProxy`

Convenience facade for the five main guard points:

```python
guard_input(...)
guard_plan(...)
guard_retrieval(...)
guard_memory_write(...)
guard_tool_call(...)
guard_tool_result(...)
guard_output(...)
```

`GuardedAgentRuntime`

Reusable runtime integration that orchestrates the full agent loop. It accepts an
`AgentRunSpec`, calls an `LLMClient` for planning and final answering, executes
tools through a `ToolExecutor`, and checks every boundary with `GuardrailProxy`.

`LLMClient`

Adapter protocol for local, hosted, or test model backends. Current built-in
implementations are `LocalTransformersLLM` and `StaticLLMClient`.

`ToolExecutor`

Adapter protocol for framework tools. `ToolRegistry` is a simple callable-backed
implementation for direct Python tools.

## Current Policies

- `PromptInjectionPolicy`: detects jailbreaks, prompt injection, fake system
  instructions, and prompt leakage requests.
- `TaskAlignmentPolicy`: checks whether plans and tool intents serve the
  declared user goal.
- `RetrievalTrustPolicy`: degrades low-trust retrieved documents and filters
  untrusted prompt-injection text before model context.
- `MemoryWritePolicy`: controls scoped memory writes and long-term persistence
  from untrusted sources.
- `ToolPermissionPolicy`: checks tool allowlists, high-risk tools, sensitive
  arguments, and dangerous filesystem or shell parameters.
- `ToolResultInspectionPolicy`: filters secrets and injected tool results.
- `OutputSafetyPolicy`: blocks system prompt leakage and filters secrets or
  personal information in final answers.
- `AuditLoggingPolicy`: records JSONL or in-memory decision traces without
  changing final decisions.

## Add A Policy

Create a new module under `src/agent_guardrail/policies/`:

```python
from dataclasses import dataclass, field

from agent_guardrail import AgentEvent, Decision, DecisionType, Policy, RailType


@dataclass
class MyPolicy(Policy):
    policy_id: str = "my_policy"
    rail_types: set[RailType] = field(default_factory=lambda: {RailType.INPUT})

    def evaluate(self, event: AgentEvent) -> Decision:
        if "bad marker" in str(event.content).lower():
            return Decision(DecisionType.BLOCK, policy_id=self.policy_id, reason="bad marker")
        return Decision.allow(self.policy_id)
```

Then export it from `src/agent_guardrail/policies/__init__.py` and optionally
`src/agent_guardrail/__init__.py`.

## Add A Runtime Or Framework Adapter

Adapters should be thin. For full agent-loop integration, build an `AgentRunSpec`
and call `GuardedAgentRuntime`:

```python
runtime.run(
    AgentRunSpec(
        user_input=user_message,
        retrieval_docs=docs,
        tool_requests=[ToolRequest(name="search", args={"query": query})],
    )
)
```

For lower-level integration, translate framework-specific callbacks into
`AgentEvent` objects:

```python
class MyAdapter:
    framework = "my-agent-runtime"

    def on_tool_start(self, name: str, args: dict) -> AgentEvent:
        return AgentEvent.from_tool_call(name, args, framework=self.framework)
```

The engine and policies should continue to read only normalized `AgentEvent`
fields.

## Future Research Extensions

The rule-based prototype can be replaced or strengthened with:

- LLM-based prompt injection detector
- MELON-style masked re-execution
- Task Shield-style task alignment checker
- AgentPoison-style memory poisoning detector
- AgentDAM-style data minimization guard
- OS-Harm-style GUI Action Guard

Those methods should plug in as policies that still return the same `Decision`
shape.
