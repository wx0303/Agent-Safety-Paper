from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from agent_guardrail.decisions import Decision, DecisionType, RiskLevel
from agent_guardrail.events import AgentEvent, RailType
from agent_guardrail.policies.base import Policy
from agent_guardrail.policies.patterns import (
    contains_prompt_injection,
    filter_prompt_injection,
    redact_secrets,
    sensitive_keys,
    stringify,
)


DANGEROUS_TOOL_NAMES = {"shell_exec", "write_file", "delete_file"}
DANGEROUS_ARG_MARKERS = (
    "rm -rf",
    "del /s",
    "remove-item",
    "-recurse",
    "/etc/",
    "/bin/",
    "/usr/",
    "c:\\windows",
    "c:/windows",
    "system32",
    "../",
    "..\\",
)


@dataclass
class ToolPermissionPolicy(Policy):
    """Tool execution guard for permissions, sensitive args, and dangerous actions."""

    allowed_tools: list[str] = field(default_factory=list)
    high_risk_tools: list[str] = field(default_factory=list)
    require_human_for_high_risk: bool = True
    policy_id: str = "tool_permission"
    rail_types: set[RailType] = field(default_factory=lambda: {RailType.EXECUTION})

    def __init__(
        self,
        allowed_tools: Iterable[str],
        high_risk_tools: Iterable[str] | None = None,
        require_human_for_high_risk: bool = True,
        policy_id: str = "tool_permission",
        rail_types: set[RailType] | None = None,
    ) -> None:
        self.allowed_tools = list(allowed_tools)
        self.high_risk_tools = list(high_risk_tools or [])
        self.require_human_for_high_risk = require_human_for_high_risk
        self.policy_id = policy_id
        self.rail_types = rail_types or {RailType.EXECUTION}

    def evaluate(self, event: AgentEvent) -> Decision:
        if self._is_tool_result(event):
            return Decision.allow(self.policy_id)

        tool_name = event.tool_name or event.target or event.metadata.get("tool_name")
        args = event.tool_args if event.tool_args is not None else event.content
        tool_name = str(tool_name or "")

        if tool_name in DANGEROUS_TOOL_NAMES and self._has_dangerous_args(args):
            return Decision(
                DecisionType.BLOCK,
                risk=RiskLevel.CRITICAL,
                reason=f"Dangerous arguments detected for high-impact tool '{tool_name}'.",
                policy_id=self.policy_id,
            )

        matched_sensitive_keys = sensitive_keys(args)
        if matched_sensitive_keys:
            redacted_args, _ = redact_secrets(args)
            return Decision.filter(
                risk=RiskLevel.MEDIUM,
                reason=f"Sensitive tool argument(s) filtered: {', '.join(matched_sensitive_keys)}",
                policy_id=self.policy_id,
                rewritten_content=redacted_args,
                metadata={"sensitive_keys": matched_sensitive_keys},
            )

        if tool_name in self.high_risk_tools and self.require_human_for_high_risk:
            return Decision(
                DecisionType.REQUIRE_HUMAN,
                risk=RiskLevel.HIGH,
                reason=f"High-risk tool '{tool_name}' requires human approval.",
                policy_id=self.policy_id,
            )

        if tool_name not in self.allowed_tools:
            return Decision(
                DecisionType.REQUIRE_HUMAN,
                risk=RiskLevel.HIGH,
                reason=f"Tool '{tool_name}' is not in the allowlist and requires human approval.",
                policy_id=self.policy_id,
            )

        return Decision.allow(self.policy_id)

    def _is_tool_result(self, event: AgentEvent) -> bool:
        return event.tool_result is not None or event.metadata.get("phase") == "tool_result"

    def _has_dangerous_args(self, args: Any) -> bool:
        text = stringify(args).lower()
        return any(marker in text for marker in DANGEROUS_ARG_MARKERS)


@dataclass
class ToolResultInspectionPolicy(Policy):
    """Inspects tool results for injected instructions and sensitive leakage."""

    policy_id: str = "tool_result_inspection"
    rail_types: set[RailType] = field(default_factory=lambda: {RailType.EXECUTION})

    def evaluate(self, event: AgentEvent) -> Decision:
        if event.tool_result is None and event.metadata.get("phase") != "tool_result":
            return Decision.allow(self.policy_id)

        result = event.tool_result if event.tool_result is not None else event.content
        redacted, changed = redact_secrets(result)
        if changed:
            return Decision.filter(
                risk=RiskLevel.MEDIUM,
                reason="Tool output contained secret-like content and was filtered.",
                policy_id=self.policy_id,
                rewritten_content=redacted,
            )

        if contains_prompt_injection(result):
            filtered, _ = filter_prompt_injection(result)
            return Decision.filter(
                risk=RiskLevel.MEDIUM,
                reason="Tool output contained prompt-control text and was filtered.",
                policy_id=self.policy_id,
                rewritten_content=filtered,
            )

        return Decision.allow(self.policy_id)
