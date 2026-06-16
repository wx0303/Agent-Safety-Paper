from __future__ import annotations

from typing import Any

from agent_guardrail.events import RailType
from agent_guardrail.proxy import GuardrailProxy


class LangChainMiddlewareAdapter:
    """Small placeholder adapter for LangChain middleware-style integration."""

    def __init__(self, proxy: GuardrailProxy) -> None:
        self.proxy = proxy

    def before_model(self, prompt: str, **metadata: Any) -> str:
        return self.proxy.guard_text(prompt, RailType.MODEL, phase="request", **metadata)

    def after_model(self, response: str, **metadata: Any) -> str:
        return self.proxy.guard_text(response, RailType.MODEL, phase="response", **metadata)

    def before_output(self, output: str, **metadata: Any) -> str:
        return self.proxy.guard_text(output, RailType.OUTPUT, **metadata)
