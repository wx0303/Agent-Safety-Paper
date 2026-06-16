"""End-to-end HTTP: the vendored wire must round-trip over a real socket.

Spins up a stdlib http.server stub PDP so we exercise the actual serialization,
headers, auth, schema check, and fail-closed paths — not a mock.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agentsec_sdk import (
    Decision,
    DecisionType,
    GuardrailClient,
    GuardrailConfig,
    HttpTransport,
)

_SCHEMA_HEADER = "X-AgentSec-Schema"


def _make_handler(*, decision: dict, server_schema: int = 1, require_token: str | None = None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence test output
            pass

        def do_POST(self):
            if require_token and self.headers.get("Authorization") != f"Bearer {require_token}":
                self.send_response(401)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", 0))
            event = json.loads(self.rfile.read(length).decode("utf-8"))
            # echo back what the SDK sent so the test can assert on the wire shape
            payload = dict(decision)
            payload.setdefault("metadata", {})["echo_rail"] = event["rail"]
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header(_SCHEMA_HEADER, str(server_schema))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _serve(handler_cls):
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture
def allow_server():
    decision = Decision(DecisionType.ALLOW, reason="ok").to_dict()
    server = _serve(_make_handler(decision=decision))
    yield server
    server.shutdown()


def _url(server) -> str:
    host, port = server.server_address
    return f"http://{host}:{port}"


def test_http_round_trip(allow_server):
    cfg = GuardrailConfig(transport="http", server_url=_url(allow_server))
    client = GuardrailClient(HttpTransport(cfg), config=cfg)
    decision = client.guard_input("hello")
    assert decision.decision == DecisionType.ALLOW
    assert decision.metadata["echo_rail"] == "input"  # the server saw our event


def test_http_auth_failure_is_fail_closed():
    decision = Decision(DecisionType.ALLOW).to_dict()
    server = _serve(_make_handler(decision=decision, require_token="secret"))
    try:
        # client sends no token -> 401 -> treated as transport failure -> BLOCK
        cfg = GuardrailConfig(transport="http", server_url=_url(server), retries=0)
        client = GuardrailClient(HttpTransport(cfg), config=cfg)
        decision = client.guard_input("hello")
        assert decision.decision == DecisionType.BLOCK
        assert decision.policy_name == "sdk.transport"
    finally:
        server.shutdown()


def test_http_schema_mismatch_raises():
    from agentsec_sdk import GuardrailSchemaError

    decision = Decision(DecisionType.ALLOW).to_dict()
    server = _serve(_make_handler(decision=decision, server_schema=2))
    try:
        cfg = GuardrailConfig(transport="http", server_url=_url(server), schema_version=1)
        transport = HttpTransport(cfg)
        with pytest.raises(GuardrailSchemaError):
            transport.evaluate({"rail": "input", "content": "x"})
    finally:
        server.shutdown()


def test_http_unreachable_is_fail_closed():
    # nothing listening on this port
    cfg = GuardrailConfig(
        transport="http", server_url="http://127.0.0.1:1", timeout=0.2, retries=0
    )
    client = GuardrailClient(HttpTransport(cfg), config=cfg)
    decision = client.guard_input("hello")
    assert decision.decision == DecisionType.BLOCK
    assert decision.metadata.get("transport_error") is True
