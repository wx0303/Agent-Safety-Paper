# agentsec-sdk

Thin **PEP (Policy Enforcement Point)** client for AgentSec. Embeds in an agent
process, exposes a `guard_*` surface, and delegates the actual policy evaluation
to a remote **`agentsec-server`** over a **transport**:

- `HttpTransport` — calls an `agentsec-server` `/v1/evaluate` endpoint (stdlib `urllib`, zero deps).
- `GrpcTransport` — calls the `agentsec-server` gRPC service. Optional: install
  the `[grpc]` extra (`pip install "agentsec-sdk[grpc]"`); without `grpcio`,
  `GrpcTransport is None`.

The SDK has **no policy logic and no in-process engine** — policy evaluation
always happens on the server. It also has **zero runtime dependencies**: the
wire types (`AgentEvent` / `Decision`) are vendored in `agentsec_sdk.wire` (pure
stdlib). Design: [`docs/sdk-design.md`](docs/sdk-design.md); interface contract:
[`docs/sdk-api.md`](docs/sdk-api.md).

## Quickstart — one line

```python
from agentsec_sdk import connect

client = connect("http://guard.internal")                      # remote HTTP
client = connect("grpc://guard:50051", auth_token="secret")    # remote gRPC ([grpc] extra)
```

`connect()` infers the transport from the target (`http(s)://…` → HTTP;
`grpc://host:port` or bare `host:port` → gRPC). There is **no local mode**;
passing `None` or `"local"` raises `ValueError`.

Then guard:

```python
from agentsec_sdk import Decision

dec = client.guard_input(user_text)             # -> Decision
out = client.guard_output(model_text)           # REWRITE redacts secrets in out.rewritten_content

result = client.guard_tool_call("send_email", args, send_email_fn)  # runs fn only if allowed
if isinstance(result, Decision):
    handle(result)                              # BLOCK / REQUIRE_HUMAN
else:
    use(result)                                 # real tool output
```

Every parameter, default, and enumerated value: [`docs/sdk-config.md`](docs/sdk-config.md).

### Explicit construction (full control)

```python
from agentsec_sdk import GuardrailClient, HttpTransport, GuardrailConfig, GuardrailContext

cfg = GuardrailConfig(transport="http", server_url="https://guard.internal", fail_mode="closed")
client = GuardrailClient(HttpTransport(cfg), config=cfg, context=GuardrailContext(framework="x"))
```

## Framework adapters

A framework binds its hooks to `guard_*` through a thin adapter. The reusable
core is `GuardrailAdapter`; a LangChain sample and a copy-me template ship in
`agentsec_sdk/adapters/`. Guide: [`docs/sdk-adapters.md`](docs/sdk-adapters.md).

```python
from agentsec_sdk import GuardrailClient, GuardrailAdapter

guard = GuardrailAdapter(client)
safe_text = guard.input(user_text)              # rewrite applied; raises if blocked
result    = guard.run_tool("send_email", args, real_fn, user_goal=goal)
clean_out = guard.output(model_text)            # redaction applied here
```

An adapter only covers the rails its framework's hooks expose (e.g. an MCP
server sees tool calls but not user input) — see the coverage table in the guide.

## Failure behaviour

`fail_mode="closed"` (default): if the server is unreachable, the SDK returns a
synthetic `BLOCK` (`policy_name="sdk.transport"`, `metadata.transport_error=True`)
and **does not** run tool callbacks. Use `"open"` only in non-prod.

## The wire contract

`agentsec_sdk.wire` is the SDK's vendored copy of the event/decision types and
their JSON serialization — the single source of truth for what goes on the wire
(`AgentEvent.to_dict()` out, `Decision.from_dict()` in). The `agentsec-server`
must conform to these shapes; keep them in lockstep. Field names and enum values
are documented in [`docs/sdk-api.md`](docs/sdk-api.md) §2/§6 and
[`docs/sdk-config.md`](docs/sdk-config.md) §7, and guarded by
`tests/test_wire_contract.py`.

## Tests

```powershell
python -m pytest tests -q
```

The core suite has no external dependencies. A scripted `FakeTransport`
(`tests/support.py`) stands in for the remote PDP, and `tests/test_http_transport.py`
runs the HTTP path against a stdlib stub server over a real socket.
`tests/test_grpc_transport.py` does the same against a real `grpc.server` — it
**skips** unless the `[grpc]` extra is installed (`pip install "agentsec-sdk[grpc]"`).
