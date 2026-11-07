"""Build Telegram message text for notifications, questions, permissions.

Every message carries a recognisable tag `<project> · <sess8>` where sess8 is
the first 8 chars of the Claude session id (matching what `/sessions` shows).
This lets the user tell apart interleaved messages from many projects/sessions
in one chat. Plain text (no Markdown) is used to avoid entity-escaping pitfalls;
all inputs are redacted by the caller.
"""

from __future__ import annotations

import json
from typing import Any, Optional

_LEVEL_ICON = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "❌"}

_REPLY_HINT = "↩︎ Reply to this message to answer."
_CONTINUE_HINT = "↩︎ Reply to continue, or /done."


def tag(project: str = "", session: str = "") -> str:
    """Build the header tag. *session* is an already-resolved display token
    (session name or short id) — see Runtime.session_label()."""
    proj = project or "Claude"
    if session:
        return f"{proj} · {session}"
    return proj


def notification(title: str, message: str, project: str = "",
                 level: str = "info", changed_files: list[str] | None = None,
                 session: str = "") -> str:
    icon = _LEVEL_ICON.get(level, "ℹ️")
    lines = [f"🤖 {tag(project, session)}", f"{icon} {title}"]
    if message:
        lines += ["", message]
    if changed_files:
        lines += ["", "Files:"]
        lines += [f"- {f}" for f in changed_files[:20]]
    return "\n".join(lines)


def question(question_text: str, context: str = "", options: list[str] | None = None,
             project: str = "", allow_free_text: bool = True,
             session: str = "") -> str:
    lines = [f"❓ {tag(project, session)}"]
    if context:
        lines += [context, ""]
    lines.append(question_text)
    if options:
        lines += [f"{i + 1}. {opt}" for i, opt in enumerate(options)]
    if allow_free_text:
        lines += ["", _REPLY_HINT]
    return "\n".join(lines)


def permission(tool_name: str, tool_input: dict[str, Any], risk_level: str,
               reason: str, project: str = "", session: str = "") -> str:
    lines = [f"⚠️ {tag(project, session)} — Permission", f"Tool: {tool_name}"]
    command = tool_input.get("command")
    if command:
        lines += ["Command:", command]
    else:
        file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if file_path:
            lines.append(f"Target: {file_path}")
        else:
            lines.append(f"Input: {json.dumps(tool_input)[:500]}")
    lines += [f"Risk: {risk_level}"]
    if reason:
        lines.append(f"Reason: {reason}")
    lines += ["", "Approve below, or reply to this message."]
    return "\n".join(lines)


def summary(summary_text: str, changed_files: list[str] | None = None,
            tests: list[dict] | None = None, next_suggestion: str = "",
            project: str = "", session: str = "") -> str:
    lines = [f"🤖 {tag(project, session)}", summary_text]
    if changed_files:
        lines += ["", "Changed:"]
        lines += [f"- {f}" for f in changed_files[:20]]
    if tests:
        lines += ["", "Tests:"]
        for t in tests:
            icon = "✅" if t.get("status") == "pass" else "❌"
            lines.append(f"{icon} {t.get('command', '')}")
    if next_suggestion:
        lines += ["", f"Next: {next_suggestion}"]
    lines += ["", _CONTINUE_HINT]
    return "\n".join(lines)
