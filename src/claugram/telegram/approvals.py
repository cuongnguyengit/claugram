"""Inline-keyboard builders and callback_data encode/decode.

callback_data format (Telegram limits it to 64 bytes):
    "q|<question_id>|<index>"     answer to a question option
    "p|<permission_id>|<decision>" permission decision (allow/deny)

Only a short id prefix is embedded; the bot resolves it against the DB.
"""

from __future__ import annotations

from typing import Optional

CB_SEP = "|"


def question_keyboard(question_id: str, options: list[str]) -> Optional[dict]:
    if not options:
        return None
    short = question_id[:16]
    buttons = []
    for idx, opt in enumerate(options):
        label = opt if len(opt) <= 32 else opt[:29] + "..."
        buttons.append([{"text": label, "callback_data": f"q{CB_SEP}{short}{CB_SEP}{idx}"}])
    return {"inline_keyboard": buttons}


def permission_keyboard(permission_id: str,
                        options: Optional[list[str]] = None) -> dict:
    short = permission_id[:16]
    options = options or ["allow_once", "deny"]
    row = []
    labels = {"allow_once": "✅ Allow once", "allow": "✅ Allow", "deny": "⛔ Deny"}
    for opt in options:
        decision = "allow" if opt.startswith("allow") else "deny"
        row.append({
            "text": labels.get(opt, opt),
            "callback_data": f"p{CB_SEP}{short}{CB_SEP}{decision}",
        })
    return {"inline_keyboard": [row]}


def parse_callback(data: str) -> Optional[tuple[str, str, str]]:
    """Return (kind, short_id, value) or None."""
    parts = data.split(CB_SEP)
    if len(parts) != 3:
        return None
    kind, short_id, value = parts
    if kind not in ("q", "p"):
        return None
    return kind, short_id, value
