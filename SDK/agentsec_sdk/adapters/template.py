"""Copy-me template: adapt the AgentSec SDK to your own framework.

An adapter does exactly three things and nothing else:
  1. translate your framework's callback signature into a ``guard_*`` call,
  2. let the ``GuardrailAdapter`` core run the policy decision,
  3. translate the result back into what your framework expects.

NO safety logic lives here — that is in the policies, on the server. Keep this
thin. Delete the rails your framework can't observe (see the coverage caveat in
docs/sdk-adapters.md): an MCP server, for instance, only sees tool calls/results.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..client import GuardrailClient
from .base import GuardrailAdapter


class FrameworkGuardrailAdapter:
    def __init__(self, client: GuardrailClient) -> None:
        self._guard = GuardrailAdapter(client)

    # 1) USER INPUT hook -----------------------------------------------------
    # def on_user_message(self, framework_event):
    #     text = framework_event.text                      # translate in
    #     safe = self._guard.input(text)                   # decision (raises if blocked)
    #     framework_event.text = safe                      # translate out (rewrite applied)
    #     return framework_event

    # 2) TOOL CALL hook ------------------------------------------------------
    # def on_tool_call(self, name, raw_args, real_callable):
    #     args = self._to_dict(raw_args)                   # translate in
    #     return self._guard.run_tool(name, args, real_callable,
    #                                 user_goal=self.goal)  # runs only if allowed

    # 3) MODEL/FINAL OUTPUT hook --------------------------------------------
    # def on_output(self, text):
    #     return self._guard.output(text)                  # redaction applied here

    # Optional rails, if your framework exposes them:
    #   self._guard.plan(step, user_goal=...)
    #   self._guard.retrieval(docs)
    #   self._guard.memory_write(key, value, scope=...)
    #   self._guard.check_tool_result(name, result)

    def example_tool_call(
        self,
        name: str,
        args: dict[str, Any],
        call: Callable[[dict[str, Any]], Any],
    ) -> Any:
        """Minimal working method so the template is importable and testable."""

        return self._guard.run_tool(name, args, call)
