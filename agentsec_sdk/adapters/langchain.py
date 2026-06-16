"""Reference adapter: LangChain.

Middleware-style hooks you wire into your chain (an LCEL ``RunnableLambda``, a
custom agent loop, or a wrapper around tool calls). Middleware can *rewrite*
content (return sanitized text), which classic observe-only callbacks cannot —
so redaction/rewrite rails work here.

This module does **not** import LangChain; it only needs a ``GuardrailClient``.
That keeps the SDK dependency-free — the LangChain dependency lives in the user's
app, which calls these hooks.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..client import GuardrailClient
from .base import GuardrailAdapter


class LangChainGuardrailMiddleware:
    """Thin LangChain binding over :class:`GuardrailAdapter`.

    Each hook maps a LangChain lifecycle point to a rail and returns the
    resolved content (raising ``GuardrailViolation`` on block / human-required).

    Example (LCEL)::

        guard = LangChainGuardrailMiddleware(client)
        chain = (
            RunnableLambda(guard.before_input)
            | prompt | llm | StrOutputParser()
            | RunnableLambda(guard.before_output)
        )

    Tool wrapping::

        def guarded_tool(args):
            return guard.run_tool("send_email", args, real_send_email)
    """

    def __init__(self, client: GuardrailClient) -> None:
        self._adapter = GuardrailAdapter(client)

    # text rails
    def before_input(self, text: str, **md: Any) -> str:
        return self._adapter.input(text, **md)

    def before_model(self, prompt: str, **md: Any) -> str:
        # Treat the assembled prompt as an input-rail check before the LLM call.
        return self._adapter.input(prompt, phase="request", **md)

    def before_output(self, text: str, **md: Any) -> str:
        return self._adapter.output(text, **md)

    # retrieval rail
    def on_retrieval(self, docs: list[dict[str, Any]], **md: Any) -> list[dict[str, Any]]:
        return self._adapter.retrieval(docs, **md)

    # execution rail
    def run_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_fn: Callable[[dict[str, Any]], Any],
        **md: Any,
    ) -> Any:
        return self._adapter.run_tool(tool_name, tool_args, tool_fn, **md)
