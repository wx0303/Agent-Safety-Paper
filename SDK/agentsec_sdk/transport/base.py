from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Transport(ABC):
    """Carries an event to a decision point and returns its decision.

    The contract is dict-in / dict-out so every transport (local engine, HTTP,
    gRPC) speaks the same wire shape: ``AgentEvent.to_dict()`` in,
    ``Decision.to_dict()`` out. Implementations raise ``TransportError`` (or a
    subclass) on infrastructure failure; the client turns that into the
    configured fail mode.
    """

    @abstractmethod
    def evaluate(self, event: dict[str, Any]) -> dict[str, Any]:
        """Evaluate one serialized event, returning a serialized decision."""

    def close(self) -> None:  # pragma: no cover - optional lifecycle hook
        """Release any held resources (connections, channels)."""
