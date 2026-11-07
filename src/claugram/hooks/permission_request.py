"""PermissionRequest / PreToolUse hook: allow / deny / ask-via-Telegram."""

from __future__ import annotations

from typing import Optional

from ..runtime import Runtime
from ..security import evaluate_tool
from ..mcp import tools
from .base import run_hook


def _decision(event_name: str, decision: str, reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "permissionDecision": decision,           # allow | deny | ask
            "permissionDecisionReason": reason,
        }
    }


def handle(event: dict, rt: Optional[Runtime]):
    event_name = event.get("hook_event_name") or "PreToolUse"
    tool_name = event.get("tool_name") or ""
    tool_input = event.get("tool_input") or {}

    if rt is None:
        return None  # not configured -> defer to Claude's own prompt

    verdict = evaluate_tool(tool_name, tool_input, rt.config)

    if verdict.action == "allow":
        return _decision(event_name, "allow", verdict.reason)
    if verdict.action == "deny":
        return _decision(event_name, "deny", verdict.reason)

    # ask -> route to Telegram, unless forwarding is off (defer to Claude's own UI)
    if not rt.forwarding_enabled():
        return None
    result = tools.do_request_permission(
        rt, tool_name, tool_input,
        risk_level=verdict.risk_level, reason=verdict.reason,
        session_id=event.get("session_id"))
    decision = "allow" if result.get("decision", "").startswith("allow") else "deny"
    msg = result.get("message") or verdict.reason
    if result.get("timed_out"):
        msg = f"No response on Telegram; applied default ({decision})."
    return _decision(event_name, decision, msg)


def main() -> None:
    run_hook(handle)


if __name__ == "__main__":
    main()
