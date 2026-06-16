"""connect(): infer a network transport from the target string."""

from __future__ import annotations

import pytest

from agentsec_sdk import GuardrailClient, HttpTransport, connect


def test_connect_http_infers_transport():
    client = connect("http://guard.internal:8088")
    assert isinstance(client, GuardrailClient)
    assert isinstance(client._transport, HttpTransport)  # noqa: SLF001


def test_connect_https_infers_transport():
    client = connect("https://guard.internal")
    assert isinstance(client._transport, HttpTransport)  # noqa: SLF001


def test_connect_local_or_none_raises():
    # local/in-process mode was removed; the SDK is HTTP/gRPC only.
    with pytest.raises(ValueError):
        connect("local")
    with pytest.raises(ValueError):
        connect(None)  # type: ignore[arg-type]


def test_connect_unknown_target_raises():
    with pytest.raises(ValueError):
        connect("ftp://nope")


def test_connect_context_string_sets_framework():
    client = connect("http://guard.internal", context="my-agent")
    assert client._context.framework == "my-agent"  # noqa: SLF001


def test_connect_passes_auth_and_timeout_to_config():
    client = connect("http://guard.internal", auth_token="secret", timeout=0.3, retries=2)
    cfg = client._config  # noqa: SLF001
    assert cfg.auth_token == "secret"
    assert cfg.timeout == 0.3
    assert cfg.retries == 2
    assert cfg.fail_mode == "closed"


def test_connect_grpc_target_when_extra_present_or_skipped():
    pytest.importorskip("grpc")
    from agentsec_sdk.transport.grpc import GrpcTransport

    client = connect("grpc://guard:50051")
    assert isinstance(client._transport, GrpcTransport)  # noqa: SLF001


def test_connect_bare_host_port_is_grpc_or_skipped():
    pytest.importorskip("grpc")
    from agentsec_sdk.transport.grpc import GrpcTransport

    client = connect("guard:50051")
    assert isinstance(client._transport, GrpcTransport)  # noqa: SLF001
