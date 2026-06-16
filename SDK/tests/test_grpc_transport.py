"""End-to-end gRPC: the vendored wire must round-trip over a real gRPC socket.

Runs an actual ``grpc.server`` on an ephemeral port (skipped when grpcio is
absent) so we exercise the real channel, JSON-in-proto contract, metadata auth,
schema check, and fail-closed paths — not a mock.
"""

from __future__ import annotations

import json
from concurrent import futures

import pytest

grpc = pytest.importorskip("grpc")  # skip the whole module without the [grpc] extra

from agentsec_sdk import (  # noqa: E402
    Decision,
    DecisionType,
    GuardrailClient,
    GuardrailConfig,
    GuardrailSchemaError,
)
from agentsec_sdk._proto import agentsec_pb2, agentsec_pb2_grpc  # noqa: E402
from agentsec_sdk.transport.grpc import GrpcTransport  # noqa: E402


class _Servicer(agentsec_pb2_grpc.GuardrailServicer):
    def __init__(self, *, decision: dict, response_schema: int = 1, require_token: str | None = None):
        self._decision = decision
        self._response_schema = response_schema
        self._require_token = require_token

    def Evaluate(self, request, context):
        if self._require_token:
            md = dict(context.invocation_metadata())
            if md.get("authorization") != f"Bearer {self._require_token}":
                context.abort(grpc.StatusCode.UNAUTHENTICATED, "missing/invalid token")
        event = json.loads(request.event_json)
        payload = dict(self._decision)
        payload.setdefault("metadata", {})["echo_rail"] = event["rail"]
        return agentsec_pb2.EvaluateResponse(
            schema_version=self._response_schema,
            decision_json=json.dumps(payload),
        )


def _serve(servicer):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    agentsec_pb2_grpc.add_GuardrailServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    return server, f"127.0.0.1:{port}"


def test_grpc_round_trip():
    decision = Decision(DecisionType.ALLOW, reason="ok").to_dict()
    server, target = _serve(_Servicer(decision=decision))
    try:
        cfg = GuardrailConfig(transport="grpc", server_url=target)
        client = GuardrailClient(GrpcTransport(cfg), config=cfg)
        result = client.guard_input("hello")
        assert result.decision == DecisionType.ALLOW
        assert result.metadata["echo_rail"] == "input"  # the server saw our event
    finally:
        server.stop(None)


def test_grpc_auth_metadata_is_passed_and_accepted():
    decision = Decision(DecisionType.ALLOW).to_dict()
    server, target = _serve(_Servicer(decision=decision, require_token="secret"))
    try:
        cfg = GuardrailConfig(transport="grpc", server_url=target, auth_token="secret")
        client = GuardrailClient(GrpcTransport(cfg), config=cfg)
        assert client.guard_input("hello").decision == DecisionType.ALLOW
    finally:
        server.stop(None)


def test_grpc_auth_failure_is_fail_closed():
    decision = Decision(DecisionType.ALLOW).to_dict()
    server, target = _serve(_Servicer(decision=decision, require_token="secret"))
    try:
        # no token -> server aborts UNAUTHENTICATED -> RpcError -> fail-closed BLOCK
        cfg = GuardrailConfig(transport="grpc", server_url=target, retries=0)
        client = GuardrailClient(GrpcTransport(cfg), config=cfg)
        result = client.guard_input("hello")
        assert result.decision == DecisionType.BLOCK
        assert result.policy_name == "sdk.transport"
        assert result.metadata.get("transport_error") is True
    finally:
        server.stop(None)


def test_grpc_schema_mismatch_raises():
    decision = Decision(DecisionType.ALLOW).to_dict()
    server, target = _serve(_Servicer(decision=decision, response_schema=2))
    try:
        cfg = GuardrailConfig(transport="grpc", server_url=target, schema_version=1)
        transport = GrpcTransport(cfg)
        with pytest.raises(GuardrailSchemaError):
            transport.evaluate({"rail": "input", "content": "x"})
    finally:
        server.stop(None)


def test_grpc_unreachable_is_fail_closed():
    # nothing listening on this port
    cfg = GuardrailConfig(
        transport="grpc", server_url="127.0.0.1:1", timeout=0.3, retries=0
    )
    client = GuardrailClient(GrpcTransport(cfg), config=cfg)
    result = client.guard_input("hello")
    assert result.decision == DecisionType.BLOCK
    assert result.metadata.get("transport_error") is True


def test_grpc_accepts_grpc_scheme_prefix():
    decision = Decision(DecisionType.ALLOW).to_dict()
    server, target = _serve(_Servicer(decision=decision))
    try:
        cfg = GuardrailConfig(transport="grpc", server_url=f"grpc://{target}")
        client = GuardrailClient(GrpcTransport(cfg), config=cfg)
        assert client.guard_input("hello").decision == DecisionType.ALLOW
    finally:
        server.stop(None)
