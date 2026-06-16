from __future__ import annotations

import json
import re
from typing import Any


PROMPT_INJECTION_BLOCK_MARKERS = (
    "ignore previous instructions",
    "ignore all previous",
    "reveal your prompt",
    "jailbreak",
    "do not follow",
    "disregard",
    "override",
    "你现在不需要遵守",
    "忽略之前的指令",
    "泄露系统提示词",
    "绕过安全规则",
)

PROMPT_INJECTION_SUSPICIOUS_MARKERS = (
    "developer message",
    "system prompt",
    "bypass",
    "ignore previous",
    "disable guardrail",
    "developer mode",
)

SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|token|password|private[_-]?key)\s*[:=]\s*['\"]?([A-Za-z0-9_\-./+=]{8,})['\"]?"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-.]{16,}"),
)

SENSITIVE_ARG_KEYS = {
    "api_key",
    "apikey",
    "token",
    "password",
    "secret",
    "private_key",
    "privatekey",
}


def stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def prompt_injection_matches(text: str) -> tuple[list[str], list[str]]:
    lower = text.lower()
    block = [marker for marker in PROMPT_INJECTION_BLOCK_MARKERS if marker.lower() in lower]
    suspicious = [
        marker for marker in PROMPT_INJECTION_SUSPICIOUS_MARKERS if marker.lower() in lower
    ]
    return block, suspicious


def contains_prompt_injection(value: Any) -> bool:
    block, suspicious = prompt_injection_matches(stringify(value))
    return bool(block or suspicious)


def filter_prompt_injection(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str):
        filtered = value
        for marker in (*PROMPT_INJECTION_BLOCK_MARKERS, *PROMPT_INJECTION_SUSPICIOUS_MARKERS):
            filtered = re.sub(re.escape(marker), "[FILTERED_PROMPT_INJECTION]", filtered, flags=re.IGNORECASE)
        return filtered, filtered != value

    if isinstance(value, dict):
        changed = False
        filtered_dict: dict[str, Any] = {}
        for key, item in value.items():
            filtered_item, item_changed = filter_prompt_injection(item)
            filtered_dict[key] = filtered_item
            changed = changed or item_changed
        return filtered_dict, changed

    if isinstance(value, list):
        changed = False
        filtered_list: list[Any] = []
        for item in value:
            filtered_item, item_changed = filter_prompt_injection(item)
            filtered_list.append(filtered_item)
            changed = changed or item_changed
        return filtered_list, changed

    return value, False


def redact_secrets(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str):
        redacted = value
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)
        return redacted, redacted != value

    if isinstance(value, dict):
        changed = False
        redacted_dict: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in SENSITIVE_ARG_KEYS:
                redacted_dict[key] = "[REDACTED_SECRET]"
                changed = True
                continue
            redacted_item, item_changed = redact_secrets(item)
            redacted_dict[key] = redacted_item
            changed = changed or item_changed
        return redacted_dict, changed

    if isinstance(value, list):
        changed = False
        redacted_list: list[Any] = []
        for item in value:
            redacted_item, item_changed = redact_secrets(item)
            redacted_list.append(redacted_item)
            changed = changed or item_changed
        return redacted_list, changed

    return value, False


def contains_secret(value: Any) -> bool:
    _, changed = redact_secrets(value)
    return changed


def sensitive_keys(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    matched: list[str] = []
    for key, item in value.items():
        normalized = str(key).lower().replace("-", "_")
        if normalized in SENSITIVE_ARG_KEYS:
            matched.append(str(key))
        matched.extend(sensitive_keys(item))
    return matched
