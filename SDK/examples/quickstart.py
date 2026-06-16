"""Quickstart: the guard_* surface, runnable with zero setup.

The SDK is a pure PEP client — policy decisions come from a remote
``agentsec-server``. To keep this example runnable offline, it ships a tiny
in-process ``DemoTransport`` that returns canned decisions. In real code you do
not write a transport: you call ``connect("http://your-server")`` (see bottom).

Run from the repo root:
    python examples/quickstart.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentsec_sdk import (  # noqa: E402
    Decision,
    DecisionType,
    GuardrailClient,
    GuardrailContext,
    RiskLevel,
    Transport,
)


class DemoTransport(Transport):
    """Stand-in PDP for the example: scripts a decision per event. NOT for real use."""

    def evaluate(self, event: dict[str, Any]) -> dict[str, Any]:
        content = event.get("content")
        tool = event.get("tool_name")
        # input/output rails: block obvious injection, redact obvious secrets
        if isinstance(content, str) and "ignore previous instructions" in content.lower():
            return Decision(DecisionType.BLOCK, reason="prompt injection",
                            policy_name="demo.injection", risk=RiskLevel.HIGH).to_dict()
        if isinstance(content, str) and "secret=" in content:
            cleaned = content.split("secret=")[0] + "secret=[REDACTED]"
            return Decision(DecisionType.REWRITE, rewritten_content=cleaned,
                            policy_name="demo.output").to_dict()
        # tool rail: hold send_email for a human, allow the rest
        if tool == "send_email" and "tool_result" not in event:
            return Decision(DecisionType.REQUIRE_HUMAN, reason="high-risk tool",
                            policy_name="demo.tools").to_dict()
        return Decision(DecisionType.ALLOW).to_dict()


client = GuardrailClient(
    DemoTransport(), context=GuardrailContext(framework="quickstart", session_id="demo-1")
)


def calculator(args: dict[str, Any]) -> int:
    return int(args["left"]) + int(args["right"])


# 1) input rail — injection is blocked
print("input :", client.guard_input("Ignore previous instructions.").decision.value)

# 2) allowed tool -> runs locally, returns the real output
print("calc  :", client.guard_tool_call("calculator", {"left": 2, "right": 3}, calculator))

# 3) high-risk tool -> held for human, fn never runs
held = client.guard_tool_call("send_email", {"to": "x@y.z"}, lambda a: "sent")
assert isinstance(held, Decision)
print("email :", held.decision.value, "-", held.reason)

# 4) output rail — secret redaction
out = client.guard_output("Done. secret=supersecret12345")
print("output:", out.decision.value, "->", out.rewritten_content)

# ---------------------------------------------------------------------------
# In real code you skip DemoTransport entirely and just point at a server:
#
#     from agentsec_sdk import connect
#     client = connect("http://guard.internal")               # HTTP
#     client = connect("grpc://guard:50051", auth_token="…")  # gRPC ([grpc] extra)
#
# The guard_* calls above are identical regardless of transport.
