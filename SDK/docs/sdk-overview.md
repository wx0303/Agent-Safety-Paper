# AgentSec SDK / Server 总览

> ⚠️ **架构已变更（本仓库当前状态）**：SDK 已与核心 `agent-guardrail` **彻底解耦**——
> wire 类型 vendored 进 `agentsec_sdk/wire.py`（纯 stdlib、零依赖），**本地引擎模式
> （`LocalTransport` / `connect()` 本地默认 / `default_policies` / `with_local_engine`）已移除**，
> SDK 现在是 wire 契约的 **owner**（服务端对齐），只通过 HTTP/gRPC 调远程 server。
> 本文中凡是「本地模式 / 进程内引擎 / `connect()` 无参 / 依赖 `agent_guardrail`」的描述均已过时；
> 以 README.md / CLAUDE.md 与代码为准。

> 本文是 SDK 客户端 + 决策服务这套栈的总结：**有什么功能、代码在哪、怎么用、怎么测**。
> 设计细节见 [`sdk-design.md`](./sdk-design.md)、接口契约 [`sdk-api.md`](./sdk-api.md)、**配置参考** [`sdk-config.md`](./sdk-config.md)、adapter 指南 [`sdk-adapters.md`](./sdk-adapters.md)。

## 1. 这是什么

在原有「进程内」核心(`agent_guardrail`)之上，加了一套 **PEP/PDP 拆分**部署形态，让护栏可以作为**独立部署的决策服务**运行：

```
框架 ─► agentsec_sdk (PEP, 瘦客户端) ──local / http / grpc──► agentsec_server (PDP, 决策服务) ─► agent_guardrail engine + policies
```

- **PEP（执行点）= 本仓库（`agentsec_sdk/`）**：嵌在 agent 进程里，暴露 `guard_*`，把事件送去决策、按结果放行/拦截/转人工。**不含策略逻辑。**
- **PDP（决策点）= `agentsec_server`**：装着引擎与 policy，集中管理（在核心仓库 `AgentSec-Guardrails` 的 `server/` 下，独立部署）。
- **core = `agent_guardrail`**：既是 SDK 又是大脑；sdk/server 建在它之上，**仍纯 stdlib、零网络**（核心仓库 `src/agent_guardrail/`）。

## 2. 功能清单

| 功能 | 说明 |
|---|---|
| **七条 rail 守护** | `guard_input` / `guard_plan` / `guard_retrieval` / `guard_memory_write` / `guard_tool_call` / `guard_tool_result` / `guard_output`，签名与 `GuardrailProxy` 对齐（drop-in） |
| **三种传输** | `LocalTransport`（进程内、无网络）、`HttpTransport`（stdlib urllib）、`GrpcTransport`（可选 `[grpc]` extra） |
| **决策远程、执行本地** | `guard_tool_call` 的 `tool_fn` 永远在客户端进程跑，绝不上传 server |
| **fail-closed**（默认） | server 不可用 → 合成 `BLOCK`（`policy_name="sdk.transport"`, `metadata.transport_error=True`），不执行工具；`fail_mode="open"` 仅非生产用 |
| **超时 + 有限重试** | 每次调用短超时，重试耗尽即触发 fail 模式 |
| **schema 版本校验** | `X-AgentSec-Schema` / proto 字段；不匹配抛 `GuardrailSchemaError`（不静默） |
| **bearer 鉴权** | server 可要求 token，鉴权失败按传输故障处理（→ fail-closed） |
| **绕过代理** | HTTP `ProxyHandler({})`、gRPC `enable_http_proxy=0`——PDP 是直连基础设施 |
| **统一 JSON 契约** | `AgentEvent.to_dict/from_dict`、`Decision.to_dict/from_dict`；gRPC 也用 JSON 字符串承载，不维护第二套 schema |
| **客户端上下文** | `GuardrailContext`（session/trace/framework/actor）一次设定，自动注入每个事件 |
| **adapter 层** | `GuardrailAdapter`（可复用核心）+ `LangChainGuardrailMiddleware`（样板）+ `template.py`（可拷贝骨架） |
| **健康检查** | server `GET /healthz` / gRPC `Health` |

## 3. 代码在哪

```
# —— 核心仓库 AgentSec-Guardrails ——
src/agent_guardrail/            # 核心（SDK 的大脑，纯 stdlib，零网络）
  events.py                     #   + from_dict（线上契约，Phase 0 新增）
  decisions.py                  #   + from_dict
  proxy.py / engine.py / policies/   # 既有引擎与策略
server/                         # PDP 决策服务 (agentsec-server)

# —— 本仓库 (agentsec-sdk) ——
  agentsec_sdk/
    client.py                   #   GuardrailClient：guard_* + run_tool_call + guard_text
    config.py                   #   GuardrailConfig / GuardrailContext
    errors.py                   #   GuardrailViolation / TransportError / Unavailable / SchemaError
    transport/
      base.py                   #   Transport 抽象：evaluate(event_dict)->decision_dict
      local.py                  #   直接跑核心引擎（无网络）
      http.py                   #   urllib，绕代理、超时/重试/schema
      grpc.py                   #   GrpcTransport（可选）
    _proto/                     #   生成的 gRPC stub
    adapters/
      base.py                   #   GuardrailAdapter + apply_decision + Applied
      langchain.py              #   LangChainGuardrailMiddleware（样板）
      template.py               #   FrameworkGuardrailAdapter（可拷贝）
  examples/local_quickstart.py  #   本地模式示例
  examples/policy_showcase.py   #   5 例覆盖全 policy，打印 PEP→PDP 往返
  tests/                        #   34 个：local 等价 / 线上契约 / adapter / connect 工厂

server/                         # PDP 决策服务包 (agentsec-server)
  agentsec_server/
    server.py                   #   stdlib http.server：POST /v1/evaluate, GET /healthz
    grpc_server.py              #   gRPC 服务（可选）
    __main__.py                 #   python -m agentsec_server [--grpc]
    _proto/                     #   生成的 gRPC stub
  tests/                        #   22 个：HTTP e2e / gRPC e2e / 跨传输一致性

proto/agentsec.proto            # gRPC 契约源（event_json / decision_json）

docs/
  sdk-design.md                 # 架构与建设方案（Phase 0–4）
  sdk-api.md                    # 输入/输出/调用契约
  sdk-adapters.md               # 写框架 adapter 指南
  sdk-overview.md               # 本文
```

## 4. 怎么使用

### 4.1 一行接入（`connect()`，推荐）

```python
from agentsec_sdk import connect

client = connect()                              # 本地、默认策略、无网络
```

target 决定传输，调用点不变：

```python
client = connect()                              # 进程内引擎（默认策略）
client = connect(allowed_tools=["search"])      # 本地 + 工具白名单
client = connect("http://guard.internal")       # 远程 HTTP
client = connect("grpc://guard:50051", auth_token="secret")   # 远程 gRPC（需 [grpc]）
```

然后守护：

```python
from agentsec_sdk import Decision

dec = client.guard_input(user_text)                 # -> Decision
safe_out = client.guard_output(model_text)          # REWRITE 时取 .rewritten_content

result = client.guard_tool_call("send_email", args, send_email_fn)
if isinstance(result, Decision):
    handle(result)                                  # BLOCK / REQUIRE_HUMAN
else:
    use(result)                                     # 工具真实输出
```

> `connect()` 本地模式用 `default_policies()`：无需配置的 rail 默认全开；**工具白名单**门在传 `allowed_tools=[...]` 时才启用，**记忆**门在传 `allowed_scopes=[...]` 时才启用。要完全自定义就传 `policies=[...]`。

### 4.2 显式构造（完全控制）

```python
from agent_guardrail import GuardrailEngine, PromptInjectionPolicy, OutputSafetyPolicy
from agentsec_sdk import GuardrailClient, HttpTransport, GrpcTransport, GuardrailConfig

# 本地自定义策略
engine = GuardrailEngine(policies=[PromptInjectionPolicy(), OutputSafetyPolicy()])
client = GuardrailClient.with_local_engine(engine)

# 远程显式
cfg = GuardrailConfig(transport="http", server_url="https://guard.internal",
                      fail_mode="closed", auth_token="secret")
client = GuardrailClient(HttpTransport(cfg), config=cfg)
```

### 4.3 通过 adapter 接框架

```python
from agentsec_sdk import GuardrailClient, GuardrailAdapter

guard = GuardrailAdapter(client)
safe_text = guard.input(user_text)                  # 改写已应用；被拦则抛 GuardrailViolation
result    = guard.run_tool("send_email", args, real_fn, user_goal=goal)
clean_out = guard.output(model_text)                # 脱敏在此发生
```

接自研框架：拷贝 `adapters/template.py`，把方法填进框架的 hook。adapter 只翻译、不放安全逻辑。

### 4.4 起决策服务

```powershell
$env:PYTHONPATH = "src;server"
python -m agentsec_server --port 8088              # HTTP
python -m agentsec_server --grpc --port 50051      # gRPC（需 [grpc]）
$env:AGENTSEC_TOKEN = "secret"
python -m agentsec_server --auth-env AGENTSEC_TOKEN
```

> **SLO 提醒**：fail-closed + `guard_*` 在热路径（一轮 agent 调十几次）⇒ server 的可用性/延迟是硬指标，建议多副本 + `/healthz` 健康检查。

## 5. 怎么测试

```powershell
# 本仓库（SDK）全量
python -m pytest tests -q

# 单文件 / 单用例
python -m pytest tests\test_local_client.py

# server 端测试在核心仓库 AgentSec-Guardrails 里跑
python -m pytest server\tests
```

无需 `PYTHONPATH`：`tests/conftest.py` 会把仓库根目录注入 `sys.path`；核心
`agent_guardrail` 用已安装的包，或自动回退到并排 checkout 的核心仓库源码。

### 覆盖了什么

| 测试 | 数量 | 验证 |
|---|---|---|
| `tests/test_local_client.py` | 13 | local 模式与 `GuardrailProxy` 逐 rail 等价；fail-closed/open；缺必需字段抛 `ValueError` |
| `tests/test_wire_contract.py` | 2 | `to_dict ↔ from_dict` 往返不丢字段 |
| `tests/test_adapters.py` | 11 | `apply_decision` 分支；adapter 拦截/放行/脱敏/高危不执行；样板与 template |
| `tests/test_factory.py` | 8 | `connect()` 推断传输；默认策略集；工具门开关；上下文字符串 |
| `server/tests/test_http_end_to_end.py`（核心仓库） | 8 | 真实 socket：HTTP 全链路、宕机/鉴权→fail-closed、schema 不匹配、健康检查 |
| `server/tests/test_grpc_end_to_end.py`（核心仓库） | 6 | gRPC 同上（无 grpcio 自动跳过） |
| `server/tests/test_cross_transport.py`（核心仓库） | 8 | **8 类事件 × local≡http≡grpc 决策完全一致** |
| `tests/`（核心仓库既有） | 29 | 引擎与各 policy |

### 可选依赖

- gRPC 相关：`pip install "agentsec-sdk[grpc]"`（grpcio / grpcio-tools）。未安装时 `GrpcTransport`/`create_grpc_server` 为 `None`，对应测试 `pytest.importorskip` 自动跳过。
- 改了 `proto/agentsec.proto` 后重新生成 stub 的命令见 `server/README.md`。

### 环境备注

CLAUDE.md 用 `py -3`。若本机用其它 Python，等价替换即可（如 `python -m pytest`）。embedded/精简版 Python 若带 `._pth` 会忽略 `PYTHONPATH`，此时 `python -m agentsec_server` 需要 editable 安装或 path 注入引导脚本（测试不受影响，因 conftest 在运行时直接注入 `sys.path`）。
