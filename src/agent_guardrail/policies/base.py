from __future__ import annotations

from abc import ABC, abstractmethod

from agent_guardrail.decisions import Decision
from agent_guardrail.events import AgentEvent, RailType


class Policy(ABC):
    """Base interface for every guardrail defense module.

    To add a new defense method:
    1. Choose which rail(s) it protects by setting rail_types.
    2. Read the normalized AgentEvent in evaluate().
    3. Return a Decision with one of: allow, filter, degrade, require_human, block.
       Use rewrite only for backward-compatible integrations that still expect it.

    Keep framework-specific logic out of policies. LangChain, OpenClaw, Hermes,
    and MCP adapters should normalize their data into AgentEvent.metadata first.
    """

    policy_id: str
    rail_types: set[RailType]

    def applies_to(self, event: AgentEvent) -> bool:
        return event.rail in self.rail_types

    @abstractmethod
    def evaluate(self, event: AgentEvent) -> Decision:
        raise NotImplementedError
