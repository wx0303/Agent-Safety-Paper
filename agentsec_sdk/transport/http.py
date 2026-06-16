from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..config import GuardrailConfig
from ..errors import GuardrailSchemaError, GuardrailUnavailable
from .base import Transport

_SCHEMA_HEADER = "X-AgentSec-Schema"


class HttpTransport(Transport):
    """HTTP/JSON transport against an ``agentsec-server`` ``/v1/evaluate`` endpoint.

    Pure-stdlib (``urllib``) so the SDK stays dependency-free. Applies the
    per-attempt timeout and bounded retries from ``GuardrailConfig``; on
    exhaustion raises ``GuardrailUnavailable`` (→ fail mode). A schema-version
    mismatch raises ``GuardrailSchemaError`` and is never retried.
    """

    def __init__(self, config: GuardrailConfig) -> None:
        if not config.server_url:
            raise ValueError("HttpTransport requires config.server_url")
        self._config = config
        self._url = config.server_url.rstrip("/") + "/v1/evaluate"
        # The guardrail PDP is infra we talk to directly; a CONNECT proxy in the
        # middle of a fail-closed hot-path call is an anti-pattern, so bypass any
        # environment proxy by default.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def evaluate(self, event: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config
        body = json.dumps(event).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            _SCHEMA_HEADER: str(cfg.schema_version),
        }
        if cfg.auth_token:
            headers["Authorization"] = f"Bearer {cfg.auth_token}"

        last_exc: Exception | None = None
        for _attempt in range(cfg.retries + 1):
            request = urllib.request.Request(
                self._url, data=body, headers=headers, method="POST"
            )
            try:
                with self._opener.open(request, timeout=cfg.timeout) as response:
                    server_schema = response.headers.get(_SCHEMA_HEADER)
                    if server_schema is not None and int(server_schema) != cfg.schema_version:
                        raise GuardrailSchemaError(
                            f"server schema {server_schema} != client {cfg.schema_version}"
                        )
                    return json.loads(response.read().decode("utf-8"))
            except GuardrailSchemaError:
                raise
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_exc = exc
                continue

        raise GuardrailUnavailable(
            f"guardrail server unreachable after {cfg.retries + 1} attempt(s): {last_exc}"
        )
