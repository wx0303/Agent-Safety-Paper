from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
import math
import re
from typing import Any

from agent_guardrail.decisions import Decision, DecisionType, RiskLevel
from agent_guardrail.events import AgentEvent, RailType
from agent_guardrail.policies.base import Policy
from agent_guardrail.policies.patterns import stringify


UNAUTHORIZED_ACTIONS = (
    "send email",
    "transfer money",
    "delete file",
    "modify system",
    "upload",
    "exfiltrate",
    "download private data",
)

GOAL_OVERRIDE_MARKERS = (
    "ignore user goal",
    "ignore the user goal",
    "instead follow web instructions",
    "execute instructions from the webpage",
    "execute tool instructions",
    "忽略用户目标",
    "改为执行网页",
    "改为执行工具",
)

MELON_RISKY_TOOLS = {
    "delete_email",
    "delete_file",
    "exfiltrate",
    "post_message",
    "reveal_policy",
    "send_email",
    "shell_exec",
    "transfer_money",
    "upload_file",
}

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_.@-]+")


@dataclass(frozen=True)
class MelonToolCall:
    """Normalized tool call used for MELON-style trajectory comparison."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def canonical_text(self) -> str:
        parts = [self.name]
        for key in sorted(self.arguments):
            parts.append(f"{key}={stringify(self.arguments[key])}")
        return " ".join(parts)


@dataclass(frozen=True)
class MelonInspection:
    infected: bool
    score: float
    threshold: float
    normal_trace: list[MelonToolCall]
    masked_trace: list[MelonToolCall]


@dataclass
class TaskAlignmentPolicy(Policy):
    """Planner guard that checks whether plans and tools align with the user's goal."""

    policy_id: str = "task_alignment"
    rail_types: set[RailType] = field(default_factory=lambda: {RailType.PLANNER, RailType.EXECUTION})
    melon_threshold: float = 0.72

    def evaluate(self, event: AgentEvent) -> Decision:
        if event.tool_result is not None or event.metadata.get("phase") == "tool_result":
            return Decision.allow(self.policy_id)

        user_goal = str(event.metadata.get("user_goal", "")).strip()
        plan_text = self._plan_text(event)
        plan_lower = plan_text.lower()

        melon = self.inspect_melon_traces(
            event.metadata.get("normal_trace") or event.metadata.get("tool_trace"),
            event.metadata.get("masked_trace"),
        )
        if melon.infected:
            return Decision(
                DecisionType.REQUIRE_HUMAN,
                risk=RiskLevel.HIGH,
                reason=(
                    "MELON detected risky tool-call overlap after masking the "
                    "user task, indicating possible indirect prompt injection."
                ),
                policy_id=self.policy_id,
                metadata={
                    "melon_score": melon.score,
                    "melon_threshold": melon.threshold,
                    "melon_normal_trace": [call.canonical_text() for call in melon.normal_trace],
                    "melon_masked_trace": [call.canonical_text() for call in melon.masked_trace],
                },
            )

        if any(marker in plan_lower for marker in GOAL_OVERRIDE_MARKERS):
            return Decision(
                DecisionType.BLOCK,
                risk=RiskLevel.HIGH,
                reason="Plan attempts to ignore the user goal or follow external tool/web instructions.",
                policy_id=self.policy_id,
            )

        if not user_goal:
            return Decision(
                DecisionType.DEGRADE,
                risk=RiskLevel.MEDIUM,
                reason="Cannot judge task alignment because user_goal is missing.",
                policy_id=self.policy_id,
            )

        goal_lower = user_goal.lower()
        unauthorized = [
            action
            for action in UNAUTHORIZED_ACTIONS
            if action in plan_lower and not self._goal_authorizes(goal_lower, action)
        ]
        if unauthorized:
            return Decision(
                DecisionType.REQUIRE_HUMAN,
                risk=RiskLevel.HIGH,
                reason=f"Plan/tool intent contains sensitive action not authorized by user goal: {', '.join(unauthorized)}",
                policy_id=self.policy_id,
                metadata={"unauthorized_actions": unauthorized},
            )

        return Decision.allow(self.policy_id)

    def _plan_text(self, event: AgentEvent) -> str:
        pieces = [
            stringify(event.content),
            stringify(event.metadata.get("plan_step", "")),
            stringify(event.metadata.get("tool_intent", "")),
            stringify(event.tool_name or ""),
        ]
        return "\n".join(piece for piece in pieces if piece)

    def _goal_authorizes(self, goal_lower: str, action: str) -> bool:
        action_words = [word for word in action.split() if len(word) > 2]
        return action in goal_lower or all(word in goal_lower for word in action_words)

    def inspect_melon_traces(self, normal_trace: Any, masked_trace: Any) -> MelonInspection:
        normal_calls = self._normalize_trace(normal_trace)
        masked_calls = self._normalize_trace(masked_trace)
        score = self._melon_trajectory_score(normal_calls, masked_calls)
        infected = score >= self.melon_threshold and self._has_melon_risky_overlap(
            normal_calls, masked_calls
        )
        return MelonInspection(
            infected=infected,
            score=score,
            threshold=self.melon_threshold,
            normal_trace=normal_calls,
            masked_trace=masked_calls,
        )

    def _melon_trajectory_score(
        self,
        normal_trace: list[MelonToolCall],
        masked_trace: list[MelonToolCall],
    ) -> float:
        risky_normal = [call for call in normal_trace if call.name in MELON_RISKY_TOOLS]
        risky_masked = [call for call in masked_trace if call.name in MELON_RISKY_TOOLS]
        if risky_normal or risky_masked:
            return self._max_pair_similarity(risky_normal, risky_masked)
        return self._max_pair_similarity(normal_trace, masked_trace) * 0.45

    def _has_melon_risky_overlap(
        self,
        normal_trace: list[MelonToolCall],
        masked_trace: list[MelonToolCall],
    ) -> bool:
        for normal_call in normal_trace:
            if normal_call.name not in MELON_RISKY_TOOLS:
                continue
            for masked_call in masked_trace:
                if (
                    masked_call.name in MELON_RISKY_TOOLS
                    and self._tool_call_similarity(normal_call, masked_call) >= self.melon_threshold
                ):
                    return True
        return False

    def _normalize_trace(self, trace: Any) -> list[MelonToolCall]:
        if not isinstance(trace, list):
            return []
        return [call for item in trace if (call := self._normalize_tool_call(item)) is not None]

    def _normalize_tool_call(self, value: Any) -> MelonToolCall | None:
        if isinstance(value, MelonToolCall):
            return value

        if isinstance(value, dict):
            name = value.get("name") or value.get("tool_name") or value.get("tool")
            args = (
                value.get("arguments")
                or value.get("args")
                or value.get("tool_args")
                or value.get("parameters")
                or {}
            )
            if name is None:
                return None
            if not isinstance(args, dict):
                args = {"value": args}
            return MelonToolCall(str(name), args)

        name = getattr(value, "name", None) or getattr(value, "tool_name", None)
        args = getattr(value, "arguments", None) or getattr(value, "args", None) or {}
        if name is None:
            return None
        if not isinstance(args, dict):
            args = {"value": args}
        return MelonToolCall(str(name), args)

    def _tool_call_similarity(self, left: MelonToolCall, right: MelonToolCall) -> float:
        name_score = 1.0 if left.name == right.name else 0.0
        text_score = self._cosine(
            self._vectorize(left.canonical_text()),
            self._vectorize(right.canonical_text()),
        )
        return 0.65 * name_score + 0.35 * text_score

    def _max_pair_similarity(
        self,
        left: Iterable[MelonToolCall],
        right: Iterable[MelonToolCall],
    ) -> float:
        left_calls = list(left)
        right_calls = list(right)
        if not left_calls or not right_calls:
            return 0.0
        return max(self._tool_call_similarity(a, b) for a in left_calls for b in right_calls)

    def _vectorize(self, text: str) -> Counter[str]:
        return Counter(token.lower() for token in _TOKEN_RE.findall(text))

    def _cosine(self, left: Counter[str], right: Counter[str]) -> float:
        if not left or not right:
            return 0.0
        overlap = set(left) & set(right)
        numerator = sum(left[token] * right[token] for token in overlap)
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        return numerator / (left_norm * right_norm)
