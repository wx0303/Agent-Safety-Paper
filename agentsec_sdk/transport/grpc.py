from __future__ import annotations

import json
from typing import Any

import grpc

from .._proto import agentsec_pb2, agentsec_pb2_grpc
from ..config import GuardrailConfig
from ..errors import GuardrailSchemaError, GuardrailUnavailable
from .base import Transport


def _target(server_url: str) -> str:
    """Accept ``grpc://host:port`` or a bare ``host:port`` target."""

    if server_url.startswith("grpc://"):
        return server_url[len("grpc://") :]
    return server_url


class GrpcTransport(Transport):
    """gRPC transport against an ``agentsec-server`` Guardrail service.

    Lives behind the optional ``[grpc]`` extra; importing this module requires
    ``grpcio``. Reuses the JSON wire contract (event/decision dicts) carried in
    string proto fields. Applies the same timeout/retry/fail-closed and schema
    checks as ``HttpTransport``. Channel is reused across calls.
    """

    def __init__(self, config: GuardrailConfig) -> None:
        if not config.server_url:
            raise ValueError("GrpcTransport requires config.server_url (host:port)")
        self._config = config
        # Disable proxying: the guardrail PDP is direct infra (mirrors the HTTP
        # transport bypassing environment proxies).
        self._channel = grpc.insecure_channel(
            _target(config.server_url), options=[("grpc.enable_http_proxy", 0)]
        )
        self._stub = agentsec_pb2_grpc.GuardrailStub(self._channel)

    def _metadata(self) -> list[tuple[str, str]]:
        if self._config.auth_token:
            return [("authorization", f"Bearer {self._config.auth_token}")]
        return []

    def evaluate(self, event: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config
        request = agentsec_pb2.EvaluateRequest(
            schema_version=cfg.schema_version,
            event_json=json.dumps(event),
        )

        last_exc: Exception | None = None
        for _attempt in range(cfg.retries + 1):
            try:
                response = self._stub.Evaluate(
                    request, timeout=cfg.timeout, metadata=self._metadata()
                )
            except grpc.RpcError as exc:
                last_exc = exc
                continue

            if response.schema_version and response.schema_version != cfg.schema_version:
                raise GuardrailSchemaError(
                    f"server schema {response.schema_version} != client {cfg.schema_version}"
                )
            return json.loads(response.decision_json)

        raise GuardrailUnavailable(
            f"guardrail gRPC server unreachable after {cfg.retries + 1} attempt(s): {last_exc}"
        )

    def close(self) -> None:
        self._channel.close()
