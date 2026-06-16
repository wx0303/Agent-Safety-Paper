# Policy Interface

Add new defense methods under:

```text
src/agent_guardrail/policies/
```

Recommended locations:

```text
src/agent_guardrail/policies/
  base.py        # shared Policy interface
  jailbreak.py   # jailbreak, prompt injection, research defense methods
  secrets.py     # secret detection and redaction
  tool_registry.py       # tool call safety and least privilege
  retrieval.py   # RAG poisoning and source trust
  memory.py      # memory and workspace write protection
```

Export new policies from:

```text
src/agent_guardrail/policies/__init__.py
src/agent_guardrail/__init__.py
```

## Unified Interface

Every defense method implements the same interface:

```python
class Policy:
    policy_id: str
    rail_types: set[RailType]

    def applies_to(self, event: AgentEvent) -> bool:
        return event.rail in self.rail_types

    def evaluate(self, event: AgentEvent) -> Decision:
        ...
```

The engine calls `evaluate()` only when the event rail is included in `rail_types`.

## Input

Policies receive one normalized `AgentEvent`:

```python
AgentEvent(
    rail=RailType.INPUT,
    content="user or tool/model content",
    framework="langchain",
    target="optional tool name or memory path",
    metadata={"any": "adapter-specific details"},
)
```

Use:

- `event.rail`: which rail is being checked.
- `event.content`: text, tool args, tool result, retrieved content, or memory content.
- `event.framework`: `langchain`, `openclaw`, `hermes`, `mcp-agent`, etc.
- `event.target`: tool name, memory path, source URI, or other primary target.
- `event.metadata`: provider-specific details normalized by adapters.

Policies should not depend directly on LangChain, OpenClaw, Hermes, or MCP internals.

## Output

Policies return one `Decision`:

```python
Decision(
    action=DecisionAction.BLOCK,
    risk=RiskLevel.HIGH,
    reason="Detected jailbreak attack.",
    policy_id="my_jailbreak_defense",
    rewritten_content=None,
    metadata={"score": 0.93},
)
```

Available actions:

- `ALLOW`: continue without changes.
- `FILTER`: automatically remove, redact, or narrow risky content, then continue.
- `BLOCK`: stop the agent flow.
- `REWRITE`: replace `event.content` with `rewritten_content`.
- `DEGRADE`: continue with lower trust, lower privilege, or fallback behavior.
- `REQUIRE_HUMAN`: pause for manual approval.

Risk levels:

- `LOW`
- `MEDIUM`
- `HIGH`
- `CRITICAL`

## Current Policies

| Policy | Rails | Action |
| --- | --- | --- |
| `KeywordPolicy` | input, output, dialog | block/filter/require_human based on config |
| `SecretRedactionPolicy` | input, output, execution | filter |
| `ToolAllowlistPolicy` | execution | require_human |
| `MemoryScopePolicy` | memory | block or require_human |
| `RetrievalTrustPolicy` | retrieval | degrade |
| `ResearchDefensePolicy` | input, dialog | block |

## Add A New Jailbreak Defense

```python
@dataclass
class MyJailbreakDefensePolicy(Policy):
    policy_id: str = "my_jailbreak_defense"
    rail_types: set[RailType] = field(
        default_factory=lambda: {RailType.INPUT, RailType.DIALOG}
    )
    threshold: float = 0.85

    def evaluate(self, event: AgentEvent) -> Decision:
        text = str(event.content)
        score = 0.0
        # Replace this line with your detector, classifier, model score, or paper method.
        # Example: score = your_detector.score(text)

        if score >= self.threshold:
            return Decision(
                action=DecisionAction.BLOCK,
                risk=RiskLevel.HIGH,
                reason=f"Jailbreak score {score:.2f} exceeded threshold.",
                policy_id=self.policy_id,
                metadata={"score": score},
            )

        return Decision.allow(self.policy_id)
```

Then export it in:

```text
src/agent_guardrail/policies/__init__.py
src/agent_guardrail/__init__.py
```

And enable it:

```python
engine = GuardrailEngine(
    policies=[
        MyJailbreakDefensePolicy(),
        SecretRedactionPolicy(),
        ToolAllowlistPolicy(allowed_tools={"calculator", "search"}),
    ]
)
```

## Which Rail Should I Use?

| Defense method | Recommended rail |
| --- | --- |
| Jailbreak detection | input, dialog |
| Prompt injection detection | input, dialog |
| Indirect prompt injection in documents | retrieval |
| RAG poisoning detection | retrieval |
| Dangerous tool detection | execution |
| Tool output sanitization before model context | execution |
| Final answer secret leakage prevention | output |
| Memory poisoning detection | memory |
| Unsafe final answer detection | output |
| Model fallback or degradation | model |
