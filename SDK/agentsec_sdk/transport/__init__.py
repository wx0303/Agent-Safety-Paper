from __future__ import annotations

from .base import Transport
from .http import HttpTransport

__all__ = ["Transport", "HttpTransport"]

# gRPC is an optional extra; only expose it when grpcio is installed.
try:
    from .grpc import GrpcTransport
except ImportError:  # pragma: no cover - exercised only without grpcio
    GrpcTransport = None  # type: ignore[assignment]
else:
    __all__.append("GrpcTransport")
