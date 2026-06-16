from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid import cycle at runtime
    from .client import GuardrailOutcome


class GuardrailError(RuntimeError):
    """Base class for all SDK errors."""


class GuardrailViolation(GuardrailError):
    """Raised by the *raising-style* helpers on a terminal decision.

    Carries the outcome so callers can inspect ``err.result.decision``.
    """

    def __init__(self, result: "GuardrailOutcome") -> None:
        super().__init__(result.decision.reason)
        self.result = result


class TransportError(GuardrailError):
    """Infrastructure failure while talking to the guardrail server.

    The client converts this into a fail-closed ``BLOCK`` (or fail-open
    ``ALLOW`` when explicitly configured) rather than letting it propagate.
    """


class GuardrailUnavailable(TransportError):
    """Server unreachable, timed out, or returned a non-success status."""


class GuardrailSchemaError(GuardrailError):
    """SDK and server disagree on the wire schema version. Never silenced."""
