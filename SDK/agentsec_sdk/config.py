from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GuardrailContext:
    """Correlation/attribution fields injected into every event.

    Set once at client construction; per-call metadata overrides these.
    """

    session_id: str | None = None
    trace_id: str | None = None
    parent_event_id: str | None = None
    framework: str = "unknown"
    actor: str | None = None
    source: str | None = None


@dataclass
class GuardrailConfig:
    """Transport/connection settings and failure behaviour.

    ``fail_mode`` is the key security knob: on transport failure the client
    synthesises a ``BLOCK`` when ``"closed"`` (default) or an ``ALLOW`` when
    ``"open"`` (debug/non-prod only).
    """

    transport: str = "http"  # "http" | "grpc"
    server_url: str | None = None
    timeout: float = 0.5  # seconds, per attempt
    retries: int = 1  # additional attempts after the first
    fail_mode: str = "closed"  # "closed" | "open"
    auth_token: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.fail_mode not in {"closed", "open"}:
            raise ValueError(f"fail_mode must be 'closed' or 'open', got {self.fail_mode!r}")
        if self.transport not in {"http", "grpc"}:
            raise ValueError(f"unsupported transport {self.transport!r}")
