"""Classify shell commands into allow / ask / deny.

Verdicts:
  "deny"  -> hard block, never run
  "ask"   -> require explicit human approval via Telegram
  "allow" -> safe to auto-allow
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass

# Read-only commands that are safe to auto-allow (first token, or git subcmd).
_SAFE_READ = {
    "ls", "dir", "cat", "type", "pwd", "echo", "head", "tail", "grep",
    "rg", "find", "which", "where", "wc", "diff", "stat", "file",
}
_SAFE_GIT_SUB = {"status", "diff", "log", "show", "branch", "remote", "rev-parse"}
_SAFE_TEST_TOKENS = {"pytest", "jest", "vitest", "mocha", "tox", "unittest"}


@dataclass
class Verdict:
    action: str  # allow | ask | deny
    reason: str


def _tokens(command: str) -> list[str]:
    return command.strip().split()


def classify_command(
    command: str,
    deny_patterns: list[str],
    ask_patterns: list[str],
) -> Verdict:
    cmd = command.strip()
    lowered = cmd.lower()

    # 1. Hard deny patterns (config-driven) take priority.
    for pat in deny_patterns:
        if _match(cmd, pat):
            return Verdict("deny", f"matches deny pattern: {pat}")

    # 2. Built-in structural deny rules.
    if re.search(r"\brm\s+-rf?\s+(/|~|\$HOME)\b", lowered):
        return Verdict("deny", "recursive delete of root/home")
    if re.search(r"\b(curl|wget|iwr|invoke-webrequest)\b.*\|\s*(sh|bash|iex|invoke-expression)", lowered):
        return Verdict("deny", "pipe-to-shell download execution")
    if re.search(r"\bgit\s+push\b.*--force", lowered):
        return Verdict("deny", "force push")
    if re.search(r"\b(mkfs|format)\b", lowered):
        return Verdict("deny", "disk format")

    # 3. Ask patterns (config-driven).
    for pat in ask_patterns:
        if _match(cmd, pat):
            return Verdict("ask", f"matches ask pattern: {pat}")

    # 4. Built-in ask rules.
    if re.search(r"\bgit\s+push\b", lowered):
        return Verdict("ask", "git push publishes code to remote")
    if re.search(r"\b(pip|pipx|npm|pnpm|yarn|poetry|cargo|gem|go)\s+(install|add|publish)\b", lowered):
        return Verdict("ask", "package install/publish")
    if re.search(r"\b(docker\s+push|kubectl|helm|terraform\s+apply|serverless\s+deploy)\b", lowered):
        return Verdict("ask", "deploy/infra command")

    # 5. Safe read-only allow.
    toks = _tokens(cmd)
    if toks:
        first = toks[0].lower()
        if first in _SAFE_READ or first in _SAFE_TEST_TOKENS:
            return Verdict("allow", "read-only / test command")
        if first == "git" and len(toks) > 1 and toks[1].lower() in _SAFE_GIT_SUB:
            return Verdict("allow", "read-only git command")

    # 6. Default: unknown command -> ask.
    return Verdict("ask", "unclassified command")


def _match(command: str, pattern: str) -> bool:
    """Match a command against a glob-ish pattern (case-insensitive)."""
    c = command.lower().strip()
    p = pattern.lower().strip()
    if fnmatch.fnmatch(c, p):
        return True
    # also treat pattern without wildcard as substring/prefix
    core = p.replace("*", "").strip()
    return bool(core) and core in c
