from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from agent_guardrail.decisions import Decision, DecisionType, RiskLevel
from agent_guardrail.events import AgentEvent, RailType
from agent_guardrail.policies.base import Policy
from agent_guardrail.policies.patterns import (
    contains_prompt_injection,
    filter_prompt_injection,
    prompt_injection_matches,
    redact_secrets,
    stringify,
)


@dataclass
class RetrievalTrustPolicy(Policy):
    """Retrieval guard that scores external documents by source trust and injection risk."""

    trusted_sources: set[str] | None = None
    trust_threshold: float = 0.4
    policy_id: str = "retrieval_trust"
    rail_types: set[RailType] = field(default_factory=lambda: {RailType.RETRIEVAL})

    def __init__(
        self,
        trusted_sources: Iterable[str] | None = None,
        trust_threshold: float = 0.4,
        policy_id: str = "retrieval_trust",
        rail_types: set[RailType] | None = None,
    ) -> None:
        self.trusted_sources = set(trusted_sources) if trusted_sources is not None else None
        self.trust_threshold = trust_threshold
        self.policy_id = policy_id
        self.rail_types = rail_types or {RailType.RETRIEVAL}

    def evaluate(self, event: AgentEvent) -> Decision:
        docs = event.retrieval_docs or self._docs_from_legacy_event(event)
        untrusted_docs = [doc for doc in docs if self._is_untrusted(doc)]

        injected_sources: list[str] = []
        for doc in untrusted_docs:
            text = stringify(doc.get("text", doc))
            block_matches, suspicious_matches = prompt_injection_matches(text)
            if block_matches or suspicious_matches:
                injected_sources.append(str(doc.get("source") or doc.get("url") or "unknown"))

        if injected_sources:
            safe_docs = [
                doc
                for doc in docs
                if str(doc.get("source") or doc.get("url") or "unknown") not in injected_sources
            ]
            return Decision.filter(
                risk=RiskLevel.MEDIUM,
                reason="Filtered untrusted retrieval document(s) containing prompt-injection markers.",
                policy_id=self.policy_id,
                rewritten_content=safe_docs,
                metadata={"filtered_sources": injected_sources},
            )

        if untrusted_docs:
            sources = [str(doc.get("source") or doc.get("url") or "unknown") for doc in untrusted_docs]
            return Decision(
                DecisionType.DEGRADE,
                risk=RiskLevel.MEDIUM,
                reason="One or more retrieval documents are below the trust threshold and will be used as low-trust context.",
                policy_id=self.policy_id,
                metadata={"low_trust_sources": sources},
            )

        return Decision.allow(self.policy_id)

    def _docs_from_legacy_event(self, event: AgentEvent) -> list[dict[str, object]]:
        source = event.source or event.metadata.get("source") or event.metadata.get("uri")
        if source is None:
            return [{"text": event.content, "source": "unknown", "trust_score": 0.0}]
        if self.trusted_sources is not None and source in self.trusted_sources:
            return [{"text": event.content, "source": source, "trust_score": 1.0}]
        return [{"text": event.content, "source": source, "trust_score": 0.0}]

    def _is_untrusted(self, doc: dict[str, object]) -> bool:
        source = doc.get("source") or doc.get("url")
        if self.trusted_sources is not None and source in self.trusted_sources:
            return False
        try:
            trust_score = float(doc.get("trust_score", 0.0))
        except (TypeError, ValueError):
            trust_score = 0.0
        return trust_score < self.trust_threshold


@dataclass
class MemoryWritePolicy(Policy):
    """Memory guard for scoped writes, poisoning, and sensitive persistence."""

    allowed_scopes: list[str] = field(
        default_factory=lambda: ["session", "user_preferences", "project_notes"]
    )
    block_long_term_from_untrusted: bool = True
    policy_id: str = "memory_write"
    rail_types: set[RailType] = field(default_factory=lambda: {RailType.MEMORY})

    def evaluate(self, event: AgentEvent) -> Decision:
        scope = str(event.metadata.get("scope") or event.target or "")
        if scope not in self.allowed_scopes:
            return Decision(
                DecisionType.BLOCK,
                risk=RiskLevel.CRITICAL,
                reason=f"Memory scope '{scope}' is not allowed.",
                policy_id=self.policy_id,
                metadata={"scope": scope, "allowed_scopes": self.allowed_scopes},
            )

        value = event.memory_value if event.memory_value is not None else event.content
        if contains_prompt_injection(value):
            filtered, changed = filter_prompt_injection(value)
            if changed:
                return Decision.filter(
                    risk=RiskLevel.MEDIUM,
                    reason="Prompt-control text was filtered before memory persistence.",
                    policy_id=self.policy_id,
                    rewritten_content=filtered,
                )
            return Decision(
                DecisionType.REQUIRE_HUMAN,
                risk=RiskLevel.HIGH,
                reason="Memory write contains prompt-injection or system-prompt control text and requires human approval.",
                policy_id=self.policy_id,
            )

        redacted, changed = redact_secrets(value)
        if changed:
            return Decision.filter(
                risk=RiskLevel.MEDIUM,
                reason="Sensitive memory content was filtered before persistence.",
                policy_id=self.policy_id,
                rewritten_content=redacted,
            )

        source = event.source or event.metadata.get("source")
        memory_type = event.metadata.get("memory_type")
        if (
            self.block_long_term_from_untrusted
            and memory_type == "long_term"
            and source == "untrusted_web"
        ):
            return Decision(
                DecisionType.REQUIRE_HUMAN,
                risk=RiskLevel.HIGH,
                reason="Long-term memory write from untrusted_web requires human approval.",
                policy_id=self.policy_id,
                metadata={"source": source, "memory_type": memory_type},
            )

        return Decision.allow(self.policy_id)
