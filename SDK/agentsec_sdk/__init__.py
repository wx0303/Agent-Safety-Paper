"""AgentSec thin SDK client (PEP).

Exposes ``guard_*`` to frameworks/adapters and delegates policy evaluation to a
remote ``agentsec-server`` over HTTP or gRPC. Contains no policy logic and no
in-process engine — see ``docs/sdk-design.md`` and ``docs/sdk-api.md``.

The wire types (``AgentEvent`` / ``Decision`` / enums) are vendored in
``agentsec_sdk.wire`` — pure stdlib, zero dependencies.
"""

from __future__ import annotations

from .wire import AgentEvent, Decision, DecisionType, RailType, RiskLevel

from .client import GuardrailClient, GuardrailOutcome
from .config import GuardrailConfig, GuardrailContext
from .factory import connect
from .adapters import (
    Applied,
    FrameworkGuardrailAdapter,
    GuardrailAdapter,
    LangChainGuardrailMiddleware,
    apply_decision,
)
from .errors import (
    GuardrailError,
    GuardrailSchemaError,
    GuardrailUnavailable,
    GuardrailViolation,
    TransportError,
)
from .transport.base import Transport
from .transport.http import HttpTransport

# Optional: only present when the [grpc] extra is installed.
try:
    from .transport.grpc import GrpcTransport
except ImportError:  # pragma: no cover
    GrpcTransport = None  # type: ignore[assignment]

__all__ = [
    "connect",
    "GuardrailClient",
    "GuardrailOutcome",
    "GuardrailConfig",
    "GuardrailContext",
    "GuardrailAdapter",
    "apply_decision",
    "Applied",
    "LangChainGuardrailMiddleware",
    "FrameworkGuardrailAdapter",
    "Transport",
    "HttpTransport",
    "GrpcTransport",
    "GuardrailError",
    "GuardrailViolation",
    "TransportError",
    "GuardrailUnavailable",
    "GuardrailSchemaError",
    # vendored wire types
    "AgentEvent",
    "Decision",
    "DecisionType",
    "RiskLevel",
    "RailType",
]
