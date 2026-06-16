"""Framework adapters: thin bindings from a framework's hooks to ``guard_*``.

``GuardrailAdapter`` (in ``base``) is the reusable translation core; concrete
bindings (``langchain``) and a copy-me ``template`` build on it. Adapters carry
no safety logic — that lives in the policies on the server.
"""

from __future__ import annotations

from .base import Applied, GuardrailAdapter, apply_decision
from .langchain import LangChainGuardrailMiddleware
from .template import FrameworkGuardrailAdapter

__all__ = [
    "GuardrailAdapter",
    "apply_decision",
    "Applied",
    "LangChainGuardrailMiddleware",
    "FrameworkGuardrailAdapter",
]
