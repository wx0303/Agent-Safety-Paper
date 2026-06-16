# AgentSec SDK 接口契约 —— 输入 / 输出 / 调用方式

> ℹ️ **现状说明**：SDK 已与核心解耦，wire 类型 vendored 进 `agentsec_sdk/wire.py`，本地
> 引擎模式已移除（详见 README.md / CLAUDE.md）。本文定义的 **`guard_*` 调用契约与 `Decision`
> 字段语义不变、仍然有效**；§6 的「线上数据形状」现以 `agentsec_sdk/wire.py` 为权威实现
> （`AgentEvent.to_dict()` / `Decision.from_dict()`），服务端对齐这份契约。

> 配套文档：架构与建设见 [`sdk-design.md`](./sdk-design.md)。
> 本文定义 `GuardrailClient` 对框架 / adapter 暴露的精确契约。

## 0. 总览

- **输入**：框架在某个 rail 的原始数据 + 该 rail 必需的 metadata。
- **输出**：统一返回 `Decision`（`guard_tool_call` 例外，见 §3.5）。
- **调用方式**：两种风格 —— ① **返回式**（拿 `Decision` 自己分支，默认）；② **抛出式**（终止性决策抛 `GuardrailViolation`，便捷）。

```
框架原始数据 ──► client.guard_*(...) ──► Decision ──► 调用方按 DecisionType 处理
                     │
                     └─ 内部：构造 AgentEvent → transport.evaluate → Decision
```

## 1. 通用输入约定

### 1.1 客户端级上下文（构造一次，自动注入每个 event）

```python
client = GuardrailClient(
    config,
    context=GuardrailContext(
        session_id="sess-123",
        trace_id="trace-abc",
        framework="langchain",
        actor="user-42",
    ),
)
```

`session_id` / `trace_id` / `parent_event_id` / `framework` / `actor` 用于关联与审计，**不必每次调用都传**。单次调用的 `**metadata` 会与客户端上下文合并（单次覆盖全局）。

### 1.2 每个 rail 必需 / 可选的 metadata

| 方法 | 必需 | 常用可选 metadata | 被哪个 policy 读取 |
|---|---|---|---|
| `guard_input` | — | `source` | PromptInjection |
| `guard_plan` | `user_goal` | `tool_intent` | TaskAlignment |
| `guard_retrieval` | docs 内每条含 `text`,`source` | 每条 `trust_score`,`url` | RetrievalTrust |
| `guard_memory_write` | `scope` | `source`,`memory_type`(`short_term`/`long_term`) | MemoryWrite / RetrievalMemory |
| `guard_tool_call` | `tool_name`,`tool_args` | `user_goal`,`tool_intent` | ToolPermission / TaskAlignment |
| `guard_tool_result` | `tool_name` | — | ToolResultInspection |
| `guard_output` | — | — | OutputSafety |

> **缺必需字段的后果**：server 端策略拿不到判据 → 可能误判或直接返回 `REQUIRE_HUMAN`（如 memory 缺 target）。SDK 在客户端做**前置校验**，缺必需字段直接抛 `ValueError`，不发网络请求。

## 2. 统一输出：`Decision`

所有 `guard_*` 返回（或在 `Any` 分支里可得到）`Decision`，字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `decision` | `DecisionType` | `ALLOW` / `REWRITE` / `DEGRADE` / `REQUIRE_HUMAN` / `BLOCK` |
| `reason` | `str` | 人类可读原因 |
| `policy_name` | `str?` | 触发的 policy（`sdk.transport` 表示传输故障合成） |
| `severity` | `int` | 0–4，越大越严重 |
| `rewritten_content` | `Any?` | `REWRITE`/`DEGRADE` 时的替换内容 |
| `risk` | `RiskLevel` | `low`/`medium`/`high`/`critical` |
| `metadata` | `dict` | 附加信息；传输故障时含 `transport_error=true` |

### 2.1 调用方处理契约（每种 DecisionType 必须如何响应）

| DecisionType | 调用方动作 | 用哪个内容继续 |
|---|---|---|
| `ALLOW` | 正常继续 | 原始内容 |
| `REWRITE` | 继续，但**替换**为改写内容 | `decision.rewritten_content` |
| `DEGRADE` | 降级继续（能力/内容受限） | `decision.rewritten_content`（降级版） |
| `REQUIRE_HUMAN` | **暂停**，转人工审批，**未批准前不继续** | —（审批通过后再走，见 §4） |
| `BLOCK` | **终止**，不继续，向上层报 `reason` | — |

> `REWRITE`/`DEGRADE` 必带 `rewritten_content`；若为空，调用方按 `BLOCK` 保守处理。

## 3. 各方法精确签名与语义

### 3.1 `guard_input`
```python
def guard_input(self, text: str, **metadata) -> Decision
```
- **输入**：用户原始输入文本。
- **典型输出**：`REWRITE`（清洗）/ `REQUIRE_HUMAN`（疑似提示注入标记）/ `BLOCK` / `ALLOW`。
- **调用**：`REWRITE` 时用 `rewritten_content` 作为后续真正喂给模型的输入。

### 3.2 `guard_plan`
```python
def guard_plan(self, plan_step: str, user_goal: str, **metadata) -> Decision
```
- **输入**：单步计划文本 + **必需** `user_goal`（对齐判据）；可选 `tool_intent`。
- **典型输出**：`REQUIRE_HUMAN`（计划含用户目标未授权的敏感动作）/ `ALLOW`。

### 3.3 `guard_retrieval`
```python
def guard_retrieval(self, docs: list[dict], **metadata) -> Decision
```
- **输入**：检索结果列表，每条至少 `{"text","source"}`，建议带 `trust_score`(0–1)、`url`。
- **典型输出**：`REWRITE`（剔除注入片段，`rewritten_content` 为净化后的 docs）/ `DEGRADE` / `BLOCK`。
- **调用**：用 `rewritten_content` 替换原 docs 再喂给模型。

### 3.4 `guard_memory_write`
```python
def guard_memory_write(self, key: str, value: Any, scope: str, **metadata) -> Decision
```
- **输入**：`key`/`value` + **必需** `scope`；建议 `source`、`memory_type`。
- **典型输出**：`REQUIRE_HUMAN`（来自 `untrusted_web` 的长期记忆写入）/ `BLOCK`（scope 不允许）/ `ALLOW`。

### 3.5 `guard_tool_call`（唯一的特例：可能执行回调）
```python
def guard_tool_call(
    self, tool_name: str, tool_args: dict,
    tool_fn: Callable[[dict], Any] | None = None, **metadata,
) -> Any | Decision
```
**返回值是多态的**，调用方必须判别：

| 情形 | 返回 |
|---|---|
| 入参决策为 `BLOCK`/`REQUIRE_HUMAN` | 返回 `Decision`（**不执行** `tool_fn`） |
| `tool_fn is None`（只校验不执行） | 返回入参 `Decision` |
| 入参 `ALLOW` 且传了 `tool_fn` | **本地执行** `tool_fn(safe_args)`，再对结果做 `guard_tool_result`；结果非 `ALLOW` 返回该 `Decision`，否则返回**工具原始输出** |

```python
result = client.guard_tool_call("send_email", args, send_email_fn, user_goal=goal)
if isinstance(result, Decision):
    handle_block_or_human(result)      # 被拦或需审批
else:
    use(result)                        # 工具真实输出
```

- **决策远程、执行本地**：`tool_fn` 始终在 agent 进程跑，绝不上传 server。
- `safe_args` 取自入参决策的（可能被改写的）内容。

### 3.6 `guard_tool_result`
```python
def guard_tool_result(self, tool_name: str, result: Any, **metadata) -> Decision
```
- **输入**：工具返回值。**典型输出**：`REWRITE`（脱敏，如抹掉 `api_key=...`）/ `BLOCK` / `ALLOW`。

### 3.7 `guard_output`
```python
def guard_output(self, text: str, **metadata) -> Decision
```
- **输入**：拟输出给用户的最终文本。**典型输出**：`REWRITE`（脱敏）/ `BLOCK` / `ALLOW`。

## 4. 调用方式（框架 / adapter 集成范式）

### 4.1 返回式（默认，最灵活）
```python
dec = client.guard_input(user_text)
if dec.decision is DecisionType.BLOCK:
    return refuse(dec.reason)
if dec.decision is DecisionType.REQUIRE_HUMAN:
    return route_to_human(dec)
text = dec.rewritten_content if dec.rewritten_content is not None else user_text
```

### 4.2 抛出式（便捷，适合 input/output 这类纯文本 rail）
```python
try:
    safe_text = client.guard_text(user_text, RailType.INPUT)   # BLOCK/REQUIRE_HUMAN 抛 GuardrailViolation
except GuardrailViolation as e:
    return refuse(e.result.decision.reason)
```

### 4.3 工具执行（推荐用 `run_tool_call` 包装）
```python
try:
    output = client.run_tool_call("delete_file", args, delete_fn, user_goal=goal)
except GuardrailViolation as e:        # BLOCK 或 REQUIRE_HUMAN
    return route_to_human_or_refuse(e.result)
```

### 4.4 adapter 薄壳示例（框架自主回调 → 调 client）
```python
class SomeFrameworkAdapter:
    def __init__(self, client): self.client = client

    def on_user_input(self, text):                 # 框架回调
        return _apply(self.client.guard_input(text), text)

    def on_tool_call(self, name, args, fn):         # 框架回调
        return self.client.run_tool_call(name, args, fn)

    def on_output(self, text):                      # 框架回调
        return _apply(self.client.guard_output(text), text)
```
> adapter 只做「翻译签名 + 调 `guard_*` + 翻译返回」，无安全逻辑。

## 5. 错误模型（与 fail-closed 一致）

| 情形 | SDK 行为 |
|---|---|
| 缺必需输入字段 | **本地** 抛 `ValueError`，不发请求 |
| server 超时 / 拒连 / 5xx（重试耗尽） | **fail-closed**：合成 `Decision(BLOCK, policy_name="sdk.transport", metadata={"transport_error": true})` |
| schema 版本不匹配 | 抛 `GuardrailSchemaError`（不静默） |
| 鉴权失败 | server 返回 401 → 视为传输故障 → fail-closed |

- **返回式**：传输故障表现为一个 `BLOCK` 决策（带 `transport_error`），调用方可据此区分「策略拦截」与「基础设施故障」并告警。
- **抛出式**：传输故障的合成 `BLOCK` 同样触发 `GuardrailViolation`。

## 6. 输入 / 输出数据形状（线上）

- **请求体** = `AgentEvent.to_dict()`（见 `events.py`），含 `rail`/`content`/`metadata`/各 `tool_*`/`memory_*`/`retrieval_docs`/关联 id/`timestamp`。
- **响应体** = `Decision.to_dict()`（见 `decisions.py`）。
- 反序列化 `from_dict` 待在 `agentsec-contract` 补齐（Phase 0）。
- `content` 是**多态**的：INPUT/OUTPUT 为 `str`，EXECUTION 为 `dict`(args) 或工具结果，RETRIEVAL 为 `list[dict]`，MEMORY 为记忆值。序列化时按 rail 决定，调用方无需关心。

## 7. 待办

- [ ] 定 `GuardrailContext` 字段与合并规则
- [ ] 定 `GuardrailSchemaError` / `GuardrailUnavailable` 异常层级
- [ ] `_apply(decision, original)` 帮助函数（返回 `(proceed: bool, content)`）规范
- [ ] 与 `sdk-design.md` 的 Phase 1 对齐实现
