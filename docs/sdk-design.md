# AgentSec 瘦 SDK 客户端 —— 设计与建设方案

> ⚠️ **后续决策已覆盖本设计稿的一部分**：本仓库已将 SDK 与核心 `agent-guardrail`
> **彻底解耦**——把契约层（`AgentEvent`/`Decision`/枚举 + `to_dict`/`from_dict`）**vendored
> 进 `agentsec_sdk/wire.py`**（即第 2 节规划的 `agentsec-contract`，但以副本而非独立包形态落地），
> 并**移除了本地引擎模式**（`LocalTransport` / `connect()` 本地兜底 / `default_policies`）。
> 因此第 6 节「本地模式=自动兜底」与第 7 节 Phase 1（local 模式）已不再适用；
> SDK 现在是纯 HTTP/gRPC 客户端、wire 契约的 owner。以 README.md / CLAUDE.md 与代码为准。

> 状态：设计稿（已定关键选型）
> 关键决策：**fail 模式 = fail-closed**；**transport = HTTP + gRPC**

## 1. 目标与边界

SDK 是 **PEP（Policy Enforcement Point，执行点）**：嵌在 agent 进程里，把框架事件送去 server 决策，再按 `Decision` 执行。策略评估在 server（PDP，决策点），SDK 不含任何策略逻辑。

| 做 | 不做 |
|---|---|
| 暴露 `guard_*` 给框架 / adapter 调 | ❌ 不含任何 policy 逻辑 |
| 把 `AgentEvent` 序列化 → RPC 调 server | ❌ 不做 engine 评估（在 server） |
| 拿回 `Decision`，翻译成框架能懂的放行 / 拦截 / 转人工 | ❌ 不写审计落盘（server 负责） |
| 处理超时 / 重试 / 失败降级 | ❌ 不依赖任何重型框架 |

**核心契约**：SDK 的 `guard_*` 签名必须与现仓库 `GuardrailProxy.guard_*` 完全一致，使本地内嵌模式与远程模式 drop-in 互换。

## 2. 整体架构：三包 + 一份共享契约

抽出纯 stdlib 的契约层，server 与 sdk 都依赖它，避免“策略写两份 / 类型漂移”：

```
agentsec-contract   ← AgentEvent / Decision / RailType + 序列化(to_dict/from_dict)。纯 stdlib，零依赖
      ▲                    ▲
      │                    │
agentsec-core         agentsec-sdk(本方案)
(engine+policies)      ├─ GuardrailClient   ← guard_* 门面
      ▲                ├─ Transport(抽象)  ← HTTP / gRPC / Local
agentsec-server        ├─ Config           ← url/超时/重试/fail 模式/auth
(import core,          └─ adapters/        ← 各框架薄壳(调 guard_*)
 包成 API 端点)
```

- `agentsec-core` = 现仓库核心，几乎不动。
- `agentsec-contract` 从现有 `events.py` / `decisions.py` 抽出（二者已有 `to_dict`，只需补 `from_dict`）。

> 详细的输入 / 输出 / 调用方式契约见 [`sdk-api.md`](./sdk-api.md)。

## 3. SDK 公共 API（与 proxy 对齐，框架 / adapter 调它）

```python
class GuardrailClient:
    def __init__(self, config: GuardrailConfig): ...

    def guard_input(self, text, **md) -> Decision: ...
    def guard_plan(self, plan_step, user_goal, **md) -> Decision: ...
    def guard_retrieval(self, docs, **md) -> Decision: ...
    def guard_memory_write(self, key, value, scope, **md) -> Decision: ...
    def guard_tool_call(self, tool_name, tool_args, tool_fn=None, **md) -> Any | Decision: ...
    def guard_tool_result(self, tool_name, result, **md) -> Decision: ...
    def guard_output(self, text, **md) -> Decision: ...
```

`guard_tool_call` 的 `tool_fn` **永远在客户端本地执行**（工具是 agent 的能力，不搬去 server）。流程：

```
构造 event → RPC 取 request 决策 → allow 才本地跑 tool_fn → 把 result 再 RPC 一次 guard_tool_result
```

即「决策远程、执行本地」。

## 4. SDK 内部结构

```
agentsec_sdk/
  client.py        # GuardrailClient：构造 event、调 transport、组装 guard_tool_call 流程
  config.py        # GuardrailConfig：server_url, timeout, retries, fail_mode, auth_token, mode
  transport/
    base.py        # Transport 抽象：evaluate(event_dict) -> decision_dict
    http.py        # transport 之一：stdlib urllib（或可选 httpx）
    grpc.py        # transport 之一：gRPC stub
    local.py       # 本地兜底：直接 import agentsec_core 跑 engine(无网络)
  errors.py        # GuardrailUnavailable 等
  adapters/        # langchain.py / autogen.py …(框架薄壳，调 client.guard_*)
```

**Transport 抽象**是关键扩展点：HTTP / gRPC / Local 都实现同一个 `evaluate(event_dict) -> decision_dict`，换传输不改 client。

## 5. 线上传输契约

复用现成序列化，仅补反向：

- **请求**：`AgentEvent.to_dict()`（已存在）。
- **响应**：`Decision.to_dict()`（已存在）。
- **要补**：`AgentEvent.from_dict()`（server 用）+ `Decision.from_dict()`（SDK 用），放进 `agentsec-contract`。
- **schema 版本号**：HTTP 用 header `X-AgentSec-Schema: 1`；gRPC 放 request 字段。SDK / server 版本不一致时明确报错，不静默出错。

### HTTP 端点

- `POST /v1/evaluate`，body = event JSON，返回 decision JSON。
- 鉴权：`Authorization: Bearer <token>`，传输走 TLS。

### gRPC 服务

```proto
service Guardrail {
  rpc Evaluate(EvaluateRequest) returns (EvaluateResponse);
}
```

- `EvaluateRequest` 内嵌 event（可用 `google.protobuf.Struct` 承载 polymorphic content，或 JSON string 字段，先 JSON string 最省事）+ `schema_version`。
- 用于低延迟 / 内网高频场景；HTTP 用于通用 / 跨语言 / 易调试场景。两者共用同一份 server 端评估逻辑。

## 6. 关键设计决策（已定）

| 决策点 | 选定 | 说明 |
|---|---|---|
| **server 不可用时** | **fail-closed** | server 超时 / 拒连 / 5xx 时，SDK 返回一个合成的 `BLOCK` 决策（`policy_name="sdk.transport"`, `reason="guardrail server unavailable"`），**不放行**。`guard_tool_call` 因此不执行 `tool_fn`。 |
| **transport** | **HTTP + gRPC** | 两者并存，由 `config.transport` 选择；共用 server 端评估逻辑与契约。 |
| **超时 / 重试** | 短超时 + 有限重试 | 默认 timeout 500ms，最多重试 1 次；重试耗尽即触发 fail-closed。 |
| **同步 / 异步** | 先 sync | 预留 `AsyncGuardrailClient` 接口位。 |
| **性能** | 连接复用 | HTTP keep-alive 连接池 / gRPC channel 复用；一轮 agent 多次 `guard_*` 不重建连接。 |
| **本地模式** | 自动兜底 | 未配 `server_url` 时用 `transport/local.py` 直接跑 core，零网络，兼容现有「无网络」定位。 |
| **认证** | bearer token + TLS | 配置项提供。 |

### fail-closed 的影响与注意

- 安全优先：server 不可用宁可拦死也不放行。
- 但 `guard_*` 在热路径、一轮调十几次，server 抖动会直接让 agent 不可用 → **server 的可用性 / 延迟是硬性 SLO**，建议 server 侧多副本 + 健康检查。
- 合成 BLOCK 决策需带明确 `metadata.transport_error=true`，便于上层区分「策略拦截」与「基础设施故障」并做告警。
- 可留一个**显式逃生开关**（如 `config.fail_mode="open"`）供非生产 / 调试环境覆盖，但默认 closed。

## 7. 建设步骤（分阶段，可独立验证）

**Phase 0 — 抽契约层**
- 从 `events.py` / `decisions.py` 抽出 `agentsec-contract`，补 `from_dict`。core 改为依赖它。现有测试全绿即通过。

**Phase 1 — SDK 本地模式（无网络，先打通 API）**
- 写 `GuardrailClient` + `transport/local.py`（直接 import core）。
- 通过和现有 `GuardrailProxy` 同一套行为测试（drop-in 验证）。
- 交付：行为等价于现 proxy、但已是客户端结构的 SDK。

**Phase 2 — HTTP transport + server 端点**
- 给现仓库加最小 `agentsec-server`（stdlib `http.server` 或可选 FastAPI），暴露 `/v1/evaluate` 调 `engine.evaluate`。
- 写 `transport/http.py`，落地 fail-closed、超时、重试、schema 版本校验、bearer 鉴权。
- 端到端测：SDK → HTTP → server → Decision；以及故障路径触发 fail-closed。

**Phase 3 — gRPC transport**
- 定义 proto，生成 stub，写 `transport/grpc.py` + server 侧 gRPC 服务（复用同一评估逻辑）。
- 契约测试：HTTP 与 gRPC 对同一 event 返回一致 Decision。

**Phase 4 — 框架 adapter**
- 把 `LangChainMiddlewareAdapter` 移入 SDK `adapters/`，补全 tool / retrieval rail，作为「标准样板」。
- 文档：用户如何照样板对接自研框架。

**Phase 5（可选）** — 异步客户端、本地预筛优化、MCP transport。

## 8. 测试策略

- **契约测试**：同组 event 固定输入 → 期望 Decision，local / HTTP / gRPC 三种 transport 结果必须一致。
- **drop-in 测试**：现有 `tests/` 中 proxy 用例换成 `GuardrailClient` 跑一遍，结果不变。
- **故障注入**：server 超时 / 5xx / 拒连 → 验证 fail-closed（返回 BLOCK 且不执行 tool_fn）。
- **schema 版本不匹配** → 明确报错。
- **鉴权**：缺 / 错 token → server 拒绝，SDK 走 fail-closed。

## 9. 与现有 CLAUDE.md 的衔接（需更新）

现 CLAUDE.md 写「核心无网络依赖」。拆分后补充：

> core / contract 仍零网络依赖；网络仅存在于 sdk 的 http/grpc transport 与 server，二者均为可选层，本地模式（local transport）不引入网络。

这样既扩展架构，又不破坏「核心纯 stdlib、无网络」的原则。

## 10. 待办 / 下一步

- [x] Phase 0：`from_dict` 反序列化契约（暂留在 `agent_guardrail`，独立 `agentsec-contract` 包后续再抽）
- [x] Phase 1：`GuardrailClient` + `LocalTransport` + fail-closed + drop-in 测试（`sdk/`）
- [x] Phase 2：`HttpTransport` + `agentsec-server`（`/v1/evaluate`）+ 端到端测试（`server/`）
- [x] Phase 3：`GrpcTransport`（可选 `[grpc]` extra）+ gRPC server + 跨 transport 一致性测试
- [x] Phase 4：adapter 层（`GuardrailAdapter` 核心 + LangChain 样板 + 可拷贝 template）+ 对接文档 [`sdk-adapters.md`](./sdk-adapters.md)
- [x] 更新 CLAUDE.md 架构说明（sdk/server/proto 三层、网络只在可选层、core 仍零网络、fail-closed、绕代理、adapter 两处）

### 落地说明（Phase 0–3 已完成）

- 代码布局：本仓库（`agentsec_sdk`，PEP 客户端）+ 核心仓库 `AgentSec-Guardrails` 下的 `server/`（`agentsec_server`，PDP）；`proto/agentsec.proto`（gRPC 契约源）两边各留一份，以核心仓库为准。均依赖核心 `agent-guardrail`。
- 选型已落实：**fail-closed** 默认、transport 抽象容纳 **local / http / grpc**。
- `from_dict` 加在 `src/agent_guardrail/events.py` 与 `decisions.py`；为减少改动暂未抽独立 contract 包，待跨包复用需求出现再抽。
- **server（PDP）**：纯 stdlib `http.server`（`POST /v1/evaluate` + `GET /healthz`）；gRPC 服务在 `grpc_server.py`（`Guardrail/Evaluate` + `Health`）。`python -m agentsec_server` 起 HTTP，`--grpc` 起 gRPC，均支持 bearer 鉴权与 schema 版本。
- **transport 一律绕过代理**：HTTP 用 `ProxyHandler({})`，gRPC 用 `grpc.enable_http_proxy=0`——guardrail PDP 是直连基础设施，热路径中间插代理是反模式。超时 + 有限重试，耗尽即 fail-closed。
- **gRPC 复用同一 JSON 契约**：proto 只有 `event_json` / `decision_json` 两个字符串字段，承载 `to_dict()`/`from_dict()`，不维护第二套 schema。生成的 stub 在各包 `_proto/`（`[grpc]` 为可选 extra，未装 grpcio 时 `GrpcTransport=None`、相关测试自动跳过）。
- 验证：`python -m pytest`（全仓 66 通过，含 HTTP/gRPC socket 端到端 + local≡http≡grpc 跨传输一致性用例）。
