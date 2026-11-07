"""Redact secrets before anything is sent to Telegram."""

from __future__ import annotations

import re

_PLACEHOLDER = "[REDACTED]"

# Ordered list of (name, compiled pattern). Patterns capture the *value* to hide.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{16,}")),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9\-_]{16,}")),
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("google_key", re.compile(r"AIza[0-9A-Za-z\-_]{20,}")),
    ("slack_token", re.compile(r"xox[baprs]-[0-9A-Za-z\-]{10,}")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("telegram_token", re.compile(r"\b\d{6,12}:[A-Za-z0-9_\-]{30,}\b")),
    ("bearer", re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]{16,}=*")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("private_key_block", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL)),
]

# key=value / key: value style secrets (env / config lines).
_KV_SECRET = re.compile(
    r"(?im)^(\s*(?:export\s+)?[A-Z0-9_]*"
    r"(?:SECRET|TOKEN|PASSWORD|PASSWD|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY)"
    r"[A-Z0-9_]*)\s*[:=]\s*(.+)$"
)


def redact(text: str | None) -> str:
    if not text:
        return "" if text is None else text
    for _name, pattern in _PATTERNS:
        text = pattern.sub(_PLACEHOLDER, text)
    text = _KV_SECRET.sub(lambda m: f"{m.group(1)}={_PLACEHOLDER}", text)
    return text


def redact_dict(data: dict) -> dict:
    """Recursively redact string values in a JSON-ish dict."""
    out: dict = {}
    for key, value in data.items():
        if isinstance(value, str):
            out[key] = redact(value)
        elif isinstance(value, dict):
            out[key] = redact_dict(value)
        elif isinstance(value, list):
            out[key] = [redact(v) if isinstance(v, str) else v for v in value]
        else:
            out[key] = value
    return out
