# SDK / Server 配置参考

> ⚠️ **架构已变更（本仓库当前状态）**：SDK 已与核心 `agent-guardrail` **彻底解耦**——
> wire 类型 vendored 进 `agentsec_sdk/wire.py`（纯 stdlib、零依赖），**本地引擎模式
> 已移除**（不再有 `LocalTransport` / `connect()` 本地默认 / `default_policies` /
> `GuardrailClient.with_local_engine`），SDK 现在是 wire 契约的 **owner**（服务端对齐）。
> `connect()` 只接受 `http(s)://` 或 `grpc://host:port` 目标。**本文 §1 的 local-only 参数
> （`policies`/`allowed_tools`/`high_risk_tools`/`allowed_scopes`）、§4（`default_policies`）、
> §5（Policy 级配置）均已不适用**；以 README.md / CLAUDE.md 与代码为准。§2/§3/§7 仍有效。

> 每个参数的含义、默认值、枚举取值，以及完整示例。总览见 [`sdk-overview.md`](./sdk-overview.md)。

## 1. `connect(...)` —— 一行接入的参数

```python
from agentsec_sdk import connect

client = connect(
    target="http://guard.internal",   # 见下表
    allowed_tools=["search", "calculator"],
    high_risk_tools=["send_email", "delete_file"],
    allowed_scopes=["session", "project_notes"],
    fail_mode="closed",
    auth_token="secret",
    timeout=0.5,
    context="my-agent",
)
```

| 参数 | 类型 | 默认 | 含义 / 枚举取值 |
|---|---|---|---|
| `target` | `str \| None` | `None` | 决定传输：`None` 或 `"local"` → 本地引擎；`"http://…"` / `"https://…"` → HTTP；`"grpc://host:port"` 或裸 `"host:port"` → gRPC |
| `policies` | `list[Policy] \| None` | `None` | 仅 local：显式策略列表，**给了就完全覆盖**默认集 |
| `allowed_tools` | `list[str] \| None` | `None` | 仅 local：工具白名单；**为 None 时不启用工具门**（未知工具不会被硬 BLOCK） |
| `high_risk_tools` | `list[str] \| None` | `None` | 仅 local：高危工具（→ `REQUIRE_HUMAN`）；None 时用内置默认表 |
| `allowed_scopes` | `list[str] \| None` | `None` | 仅 local：记忆可写 scope；**为 None 时不启用记忆门** |
| `fail_mode` | `str` | `"closed"` | 传输故障行为，枚举：`"closed"`（合成 BLOCK）/ `"open"`（合成 ALLOW，仅非生产） |
| `auth_token` | `str \| None` | `None` | 仅 http/grpc：bearer token |
| `timeout` | `float` | `0.5` | 仅 http/grpc：单次调用超时（秒） |
| `context` | `GuardrailContext \| str \| None` | `None` | 关联上下文；传字符串等价于 `GuardrailContext(framework=...)` |

> 内置高危工具默认表：`["send_email", "delete_file", "write_file", "transfer_money", "shell_exec"]`。

## 2. `GuardrailConfig` —— 传输与失败行为（显式构造时用）

```python
from agentsec_sdk import GuardrailConfig

cfg = GuardrailConfig(
    transport="http",
    server_url="https://guard.internal",
    timeout=0.5,
    retries=1,
    fail_mode="closed",
    auth_token="secret",
    schema_version=1,
)
```

| 参数 | 类型 | 默认 | 含义 / 枚举取值 |
|---|---|---|---|
| `transport` | `str` | `"local"` | 枚举：`"local"` / `"http"` / `"grpc"`（其它值在构造时抛 `ValueError`） |
| `server_url` | `str \| None` | `None` | http：`http(s)://host:port`；grpc：`host:port` 或 `grpc://host:port`。local 不需要 |
| `timeout` | `float` | `0.5` | 每次尝试的超时（秒） |
| `retries` | `int` | `1` | 首次之外的**额外**重试次数（总尝试 = `retries + 1`）；耗尽即触发 `fail_mode` |
| `fail_mode` | `str` | `"closed"` | 枚举：`"closed"` / `"open"`（其它值抛 `ValueError`） |
| `auth_token` | `str \| None` | `None` | bearer token（http 走 `Authorization` 头，grpc 走 metadata） |
| `schema_version` | `int` | `1` | 线上契约版本；与 server 不一致 → 抛 `GuardrailSchemaError` |

## 3. `GuardrailContext` —— 关联 / 溯源字段（构造一次，自动注入每个事件）

```python
from agentsec_sdk import GuardrailContext

ctx = GuardrailContext(
    session_id="sess-123",
    trace_id="trace-abc",
    parent_event_id=None,
    framework="langchain",
    actor="user-42",
    source=None,
)
```

| 参数 | 类型 | 默认 | 含义 |
|---|---|---|---|
| `session_id` | `str \| None` | `None` | 会话 id |
| `trace_id` | `str \| None` | `None` | 链路追踪 id |
| `parent_event_id` | `str \| None` | `None` | 父事件 id |
| `framework` | `str` | `"unknown"` | 来源框架标签（审计用） |
| `actor` | `str \| None` | `None` | 触发主体（用户/agent） |
| `source` | `str \| None` | `None` | 事件来源标记 |

> 单次 `guard_*(..., **metadata)` 传入的同名字段会覆盖上下文。

## 4. `default_policies(...)` —— 默认策略集开关

```python
from agentsec_sdk import default_policies, default_engine

policies = default_policies(
    allowed_tools=["search"],
    high_risk_tools=["send_email"],
    allowed_scopes=["session"],
    trust_threshold=0.4,
)
engine = default_engine(allowed_tools=["search"])   # = GuardrailEngine(policies=default_policies(...))
```

| 参数 | 类型 | 默认 | 含义 |
|---|---|---|---|
| `allowed_tools` | `list[str] \| None` | `None` | None 时**不加** `ToolPermissionPolicy`（不启用工具白名单门） |
| `high_risk_tools` | `list[str] \| None` | `None` | None 时用内置默认表 |
| `allowed_scopes` | `list[str] \| None` | `None` | None 时**不加** `MemoryWritePolicy`（不启用记忆门） |
| `trust_threshold` | `float` | `0.4` | 检索可信度阈值，`< 阈值` 视为不可信 |

**始终启用（无需配置）**：`PromptInjectionPolicy`、`TaskAlignmentPolicy`、`RetrievalTrustPolicy`、`ToolResultInspectionPolicy`、`OutputSafetyPolicy`。

## 5. Policy 级配置（自定义引擎时）

只有部分 policy 接受参数：

| Policy | 构造参数 | 默认 | 说明 |
|---|---|---|---|
| `PromptInjectionPolicy` | —（无） | | 注入/越狱标记匹配 |
| `TaskAlignmentPolicy` | —（无） | | 读事件 metadata 的 `user_goal` 判对齐 |
| `RetrievalTrustPolicy` | `trust_threshold: float` | `0.4` | 文档 `trust_score < 阈值` → 处置 |
| `MemoryWritePolicy` | `allowed_scopes: list[str]`，`block_long_term_from_untrusted: bool` | `—`，`True` | scope 白名单 + 拦截不可信源的长期记忆写入 |
| `ToolPermissionPolicy` | `allowed_tools: Iterable[str]`，`high_risk_tools: Iterable[str]`，`require_human_for_high_risk: bool` | `—`，`[]`，`True` | 工具白名单 + 高危转人工 + 危险参数 BLOCK + 敏感参数脱敏 |
| `ToolResultInspectionPolicy` | —（无） | | 工具结果脱敏 / 注入降级 |
| `OutputSafetyPolicy` | —（无） | | 系统提示泄漏 BLOCK + 输出脱敏 |
| `AuditLoggingPolicy` | `log_path: str \| None` | `None` | 给路径则额外写 JSONL 审计 |

```python
from agent_guardrail import (
    GuardrailEngine, PromptInjectionPolicy, RetrievalTrustPolicy,
    MemoryWritePolicy, ToolPermissionPolicy, ToolResultInspectionPolicy,
    OutputSafetyPolicy, AuditLoggingPolicy,
)
from agentsec_sdk import GuardrailClient

engine = GuardrailEngine(policies=[
    PromptInjectionPolicy(),
    RetrievalTrustPolicy(trust_threshold=0.5),
    MemoryWritePolicy(allowed_scopes=["session", "project_notes"],
                      block_long_term_from_untrusted=True),
    ToolPermissionPolicy(allowed_tools=["search", "calculator"],
                         high_risk_tools=["send_email", "shell_exec"],
                         require_human_for_high_risk=True),
    ToolResultInspectionPolicy(),
    OutputSafetyPolicy(),
    AuditLoggingPolicy(log_path="logs/audit.jsonl"),
])
client = GuardrailClient.with_local_engine(engine)
```

> 策略**按列表顺序执行**，顺序影响 `REWRITE` 链；引擎取最高严重级别为最终决策。

## 6. Server 端配置（PDP）

### Python API

```python
from agentsec_server import create_server, create_grpc_server

http = create_server(engine, host="0.0.0.0", port=8088,
                     auth_token="secret", schema_version=1)
grpc_srv, port = create_grpc_server(engine, host="0.0.0.0", port=50051,
                                    auth_token="secret", max_workers=8)
```

| 函数 | 参数 | 默认 | 含义 |
|---|---|---|---|
| `create_server` | `host` | `"127.0.0.1"` | 监听地址 |
| | `port` | `8088` | 端口（`0` = 临时端口，从 `server.server_address[1]` 读回） |
| | `auth_token` | `None` | 设了则要求 bearer，否则 401 |
| | `schema_version` | `1` | 响应头 `X-AgentSec-Schema` |
| `create_grpc_server` | `host` / `port` | `"127.0.0.1"` / `50051` | 同上（`port=0` 临时口，从返回的 `port` 读回） |
| | `auth_token` / `schema_version` | `None` / `1` | 同上 |
| | `max_workers` | `8` | 线程池大小 |

### 命令行

```powershell
python -m agentsec_server --host 0.0.0.0 --port 8088
python -m agentsec_server --grpc --port 50051
$env:AGENTSEC_TOKEN = "secret"; python -m agentsec_server --auth-env AGENTSEC_TOKEN
```

| 参数 | 默认 | 含义 |
|---|---|---|
| `--host` | `127.0.0.1` | 监听地址 |
| `--port` | `8088` | 端口 |
| `--auth-env` | `None` | 从该环境变量名读取 bearer token |
| `--grpc` | 关 | 启 gRPC 而非 HTTP（需 `[grpc]` extra） |

## 7. 枚举值速查

| 枚举 | 取值 | 出现处 |
|---|---|---|
| **transport** | `local` / `http` / `grpc` | `GuardrailConfig.transport` |
| **fail_mode** | `closed` / `open` | `GuardrailConfig.fail_mode`、`connect(fail_mode=)` |
| **DecisionType**（输出） | `allow` / `rewrite` / `degrade` / `require_human` / `block` | `Decision.decision` |
| **RiskLevel** | `low` / `medium` / `high` / `critical` | `Decision.risk` |
| **RailType** | `input` / `planner` / `retrieval` / `memory` / `execution` / `output` / `audit` / `model` / `dialog` | `AgentEvent.rail` |

## 8. 三档完整示例

```python
from agentsec_sdk import connect

# 1) 一行（默认策略，本地）
client = connect()

# 2) 一行带配置（本地 + 工具/记忆门 + 上下文）
client = connect(
    allowed_tools=["search", "calculator"],
    allowed_scopes=["session", "project_notes"],
    context="my-agent",
)

# 3) 远程 + fail-closed + 鉴权
client = connect("https://guard.internal", auth_token="secret",
                 fail_mode="closed", timeout=0.3)
```
