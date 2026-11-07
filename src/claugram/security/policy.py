"""Permission policy: decide allow / ask / deny for a Claude tool call."""

from __future__ import annotations

from dataclasses import dataclass

from ..config.models import Config
from . import allow_deny
from .command_classifier import classify_command, Verdict

READ_ONLY_TOOLS = {"Read", "Grep", "Glob", "LS", "NotebookRead", "WebFetch", "WebSearch"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


@dataclass
class PolicyDecision:
    action: str          # allow | ask | deny
    reason: str
    risk_level: str      # low | medium | high


def _risk_for(action: str) -> str:
    return {"deny": "high", "ask": "high", "allow": "low"}[action]


def evaluate_tool(tool_name: str, tool_input: dict, config: Config) -> PolicyDecision:
    sec = config.security

    # Strip MCP prefix for matching against bare tool names.
    bare = tool_name.split("__")[-1] if tool_name.startswith("mcp__") else tool_name

    # claugram's own bridge tools ARE the notification channel — never gate them
    # through the bridge itself, or we'd ask permission to send a summary/prompt
    # (and, for ask_user_question, block waiting on a permission for the very
    # message that asks the question). Auto-allow them.
    if tool_name.startswith(f"mcp__{config.claude.mcp_server_name}__"):
        return PolicyDecision("allow", "claugram bridge tool", "low")

    if bare in READ_ONLY_TOOLS:
        return PolicyDecision("allow", "read-only tool", "low")

    if bare == "Bash":
        command = str(tool_input.get("command", ""))
        v: Verdict = classify_command(command, sec.deny_shell_patterns, sec.ask_shell_patterns)
        return PolicyDecision(v.action, v.reason, _risk_for(v.action))

    if bare in WRITE_TOOLS:
        file_path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        if not file_path:
            return PolicyDecision("ask", "write with unknown target", "high")

        # Writing outside project root / allowed roots -> deny.
        if config.project_root and not allow_deny.is_within_roots(
            file_path, config.project_root, sec.allowed_roots
        ):
            return PolicyDecision("deny", "write outside project root", "high")

        # Sensitive files -> ask.
        if allow_deny.is_sensitive_file(file_path, sec.sensitive_file_patterns):
            return PolicyDecision("ask", f"writes sensitive file: {file_path}", "high")

        return PolicyDecision("allow", "in-project file edit", "low")

    # Unknown tool -> ask to be safe.
    return PolicyDecision("ask", f"unclassified tool: {tool_name}", "medium")
