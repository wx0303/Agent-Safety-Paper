"""One-line entry point: ``connect()``.

Infers a network transport from a target string and wires up a ready-to-use
``GuardrailClient``. The SDK is a pure PEP client: it always talks to a remote
``agentsec-server`` over HTTP or gRPC — there is no in-process engine.
"""

from __future__ import annotations

import re

from .client import GuardrailClient
from .config import GuardrailConfig, GuardrailContext
from .transport.http import HttpTransport

try:
    from .transport.grpc import GrpcTransport
except ImportError:  # pragma: no cover
    GrpcTransport = None  # type: ignore[assignment]

_HOST_PORT = re.compile(r"^[\w.\-]+:\d+$")


def _as_context(context: GuardrailContext | str | None) -> GuardrailContext | None:
    if isinstance(context, str):
        return GuardrailContext(framework=context)
    return context


def connect(
    target: str,
    *,
    fail_mode: str = "closed",
    auth_token: str | None = None,
    timeout: float = 0.5,
    retries: int = 1,
    context: GuardrailContext | str | None = None,
) -> GuardrailClient:
    """Build a ready-to-use client in one line from a server target.

    ``target``:
      - ``"http://..."`` / ``"https://..."`` -> HTTP transport.
      - ``"grpc://host:port"`` or bare ``"host:port"`` -> gRPC transport
        (requires the optional ``[grpc]`` extra).

    Examples::

        client = connect("http://guard.internal")
        client = connect("grpc://guard:50051", auth_token="secret")

    There is no local/in-process mode: policy evaluation always happens on the
    server. Passing ``None`` or ``"local"`` raises ``ValueError``.
    """

    ctx = _as_context(context)

    if target is None or target == "local":
        raise ValueError(
            "local/in-process mode has been removed; the SDK is a pure HTTP/gRPC "
            "client. Pass an 'http(s)://...' or 'grpc://host:port' target."
        )

    if target.startswith(("http://", "https://")):
        config = GuardrailConfig(
            transport="http",
            server_url=target,
            fail_mode=fail_mode,
            auth_token=auth_token,
            timeout=timeout,
            retries=retries,
        )
        return GuardrailClient(HttpTransport(config), context=ctx, config=config)

    if target.startswith("grpc://") or _HOST_PORT.match(target):
        if GrpcTransport is None:
            raise RuntimeError(
                "gRPC target given but grpcio is not installed; "
                'install the optional extra: pip install "agentsec-sdk[grpc]"'
            )
        config = GuardrailConfig(
            transport="grpc",
            server_url=target,
            fail_mode=fail_mode,
            auth_token=auth_token,
            timeout=timeout,
            retries=retries,
        )
        return GuardrailClient(GrpcTransport(config), context=ctx, config=config)

    raise ValueError(
        f"cannot infer transport from target {target!r}; "
        "use 'http(s)://...', 'grpc://host:port', or 'host:port'"
    )
