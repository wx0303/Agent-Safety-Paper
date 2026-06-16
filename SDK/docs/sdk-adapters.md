# 写一个框架 adapter

> 配套：SDK 接口契约见 [`sdk-api.md`](./sdk-api.md)。adapter 代码在 `agentsec_sdk/adapters/`。

adapter 是**框架原生 hook 与 `guard_*` 之间的薄转接层**。它只做三件事，不含任何安全逻辑（安全逻辑在 server 上的 policy 里）：

```
框架回调 ──(① 翻译入参)──► GuardrailAdapter.<rail>() ──► Decision
                                                          │
框架结果 ◄──(③ 翻译回去：改写内容 / 抛异常)──────────────┘ ②由核心裁决
```

## 三层结构

| 文件 | 角色 |
|---|---|
| `adapters/base.py` `GuardrailAdapter` | **可复用翻译核心**：每条 rail 一个方法，返回“裁决后的内容”，终止性决策抛 `GuardrailViolation` |
| `adapters/langchain.py` `LangChainGuardrailMiddleware` | **参考样板**：LangChain 绑定，薄薄包一层 `GuardrailAdapter` |
| `adapters/template.py` `FrameworkGuardrailAdapter` | **可拷贝骨架**：照着填你的框架 hook |

## 最小写法

```python
from agentsec_sdk import GuardrailClient, GuardrailAdapter

class MyFrameworkAdapter:
    def __init__(self, client: GuardrailClient):
        self._guard = GuardrailAdapter(client)

    def on_user_message(self, evt):          # 框架回调
        evt.text = self._guard.input(evt.text)   # 改写已应用；被拦则抛 GuardrailViolation
        return evt

    def on_tool_call(self, name, args, call):
        return self._guard.run_tool(name, args, call, user_goal=self.goal)

    def on_output(self, text):
        return self._guard.output(text)      # 脱敏在这里发生
```

`GuardrailAdapter` 提供的方法：`input` / `output` / `plan` / `retrieval` /
`memory_write` / `run_tool`（执行并裁决）/ `check_tool`（只裁决不执行）/
`check_tool_result`。

## 决策如何落地（adapter 的“翻译回去”）

所有 adapter 都经 `apply_decision(decision, original) -> Applied(proceed, content, decision)` 统一处理：

| 决策 | adapter 行为 |
|---|---|
| `ALLOW` | 返回原内容 |
| `REWRITE` / `DEGRADE` | 返回 `rewritten_content`（用改写后的内容继续） |
| `REQUIRE_HUMAN` / `BLOCK` | 抛 `GuardrailViolation`（`err.result.decision` 可取原因）|

> 需要“返回式”而非“抛出式”的框架，直接用 `apply_decision(...)` 拿 `Applied`，自己分支即可。

## 关键：你的框架能看到哪几条 rail？

adapter 再完整，也只能守住**框架 hook 暴露给你的 rail**。接入前先核对：

| 集成面 | 天然能拦的 rail | 拿不到的 rail |
|---|---|---|
| 自己的 agent 循环（手动埋点） | 全部 7 条 | —— |
| LangChain middleware / LCEL | input、output、tool、retrieval | 模型内部 planner（除非自己产出 plan 文本）|
| MCP server | tool_call、tool_result（resource≈retrieval）| **INPUT / PLANNER / OUTPUT**（在 host 侧，不过你的 server）|

**拿不到的 rail，就在 adapter 里删掉对应方法**——别假装覆盖。`template.py` 顶部也写了这条。

## rewrite 能不能生效，取决于 hook 类型

- **middleware / wrapper 式**（如本样板的 LangChain）：hook 能**返回**内容 → `REWRITE`/`DEGRADE` 生效（脱敏、净化检索都能落地）。
- **observe-only callback 式**（经典回调只能观察、不能改）：只能做**拦截**（block/require_human 抛异常中止），无法改写。这时把 redaction 类策略放到能改写的集成点，或文档里说明该限制。

## 测试你的 adapter

用一个**脚本化的假 PDP** 驱动 adapter 方法即可（不需要真服务端）：见
`tests/support.py` 的 `FakeTransport`（返回预设 `Decision`）与 `tests/test_adapters.py`
——clean 文本放行、注入被拦、输出脱敏、高危工具 `run_tool` 抛异常且 `tool_fn` 没被调用。
