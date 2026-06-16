from agent_guardrail import (
    GuardrailEngine,
    GuardrailProxy,
    KeywordPolicy,
    RailType,
    SecretRedactionPolicy,
    ToolAllowlistPolicy,
)


def calculator(args: dict[str, int]) -> int:
    return args["left"] + args["right"]


engine = GuardrailEngine(
    policies=[
        KeywordPolicy(policy_id="jailbreak_keywords", keywords=["disable guardrail", "exfiltrate"]),
        SecretRedactionPolicy(),
        ToolAllowlistPolicy(allowed_tools={"calculator", "search"}),
    ]
)
proxy = GuardrailProxy(engine=engine, framework="demo-agent")

safe_input = proxy.guard_text("hello, token=abc1234567890xyz", RailType.INPUT)
print(safe_input)

result = proxy.guard_tool_call("calculator", {"left": 2, "right": 3}, calculator)
print(result)
