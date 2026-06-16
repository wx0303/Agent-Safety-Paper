from __future__ import annotations

from collections.abc import Iterable

from .engine import GuardrailEngine
from .policies import (
    AuditLoggingPolicy,
    MemoryWritePolicy,
    OutputSafetyPolicy,
    PromptArmorPolicy,
    PromptInjectionPolicy,
    RetrievalTrustPolicy,
    TaskAlignmentPolicy,
    ToolPermissionPolicy,
    ToolResultInspectionPolicy,
)
from .proxy import GuardrailProxy


DEFAULT_ALLOWED_TOOLS = ("calculator", "search", "read_file")
DEFAULT_HIGH_RISK_TOOLS = (
    "send_email",
    "delete_file",
    "write_file",
    "transfer_money",
    "shell_exec",
)
DEFAULT_MEMORY_SCOPES = ("session", "user_preferences", "project_notes")


def build_default_guardrail_engine(
    *,
    allowed_tools: Iterable[str] = DEFAULT_ALLOWED_TOOLS,
    high_risk_tools: Iterable[str] = DEFAULT_HIGH_RISK_TOOLS,
    memory_scopes: Iterable[str] = DEFAULT_MEMORY_SCOPES,
    retrieval_trust_threshold: float = 0.4,
    require_human_for_high_risk_tools: bool = True,
    block_long_term_memory_from_untrusted: bool = True,
    audit_log_path: str | None = None,
) -> GuardrailEngine:
    """Build the default five-rail AgentSec policy engine."""

    policies = [
        PromptArmorPolicy(),
        PromptInjectionPolicy(),
        TaskAlignmentPolicy(),
        RetrievalTrustPolicy(trust_threshold=retrieval_trust_threshold),
        MemoryWritePolicy(
            allowed_scopes=list(memory_scopes),
            block_long_term_from_untrusted=block_long_term_memory_from_untrusted,
        ),
        ToolPermissionPolicy(
            allowed_tools=list(allowed_tools),
            high_risk_tools=list(high_risk_tools),
            require_human_for_high_risk=require_human_for_high_risk_tools,
        ),
        ToolResultInspectionPolicy(),
        OutputSafetyPolicy(),
    ]
    if audit_log_path is not None:
        policies.append(AuditLoggingPolicy(log_path=audit_log_path))
    else:
        policies.append(AuditLoggingPolicy())
    return GuardrailEngine(policies=policies)


def build_default_guardrail_proxy(
    *,
    framework: str = "agentsec-runtime",
    **engine_options: object,
) -> GuardrailProxy:
    """Build a GuardrailProxy with the default five-rail policy engine."""

    return GuardrailProxy(
        engine=build_default_guardrail_engine(**engine_options),
        framework=framework,
    )
