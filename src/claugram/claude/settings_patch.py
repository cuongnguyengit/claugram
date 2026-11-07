"""Patch .claude/settings.local.json to register claugram hooks (idempotent)."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import paths

HOOK_CMD_PREFIX = "claugram hook"

# event -> (matcher, hook sub-name, timeout seconds)
HOOK_SPECS = [
    ("PostToolUse", "Write|Edit|MultiEdit|Bash", "post-tool-use", 30),
    # Match ALL tools so every permission (MCP tools, WebFetch, unknown tools…)
    # routes through claugram -> Telegram instead of falling to the terminal
    # prompt. The policy allow-lists read-only + claugram's own bridge tools so
    # this does not spam the user. (Was "Bash|Write|Edit|MultiEdit".)
    ("PermissionRequest", "*", "permission-request", 86400),
    ("PreToolUse", "*", "permission-request", 86400),
    ("Notification", None, "notification", 30),
    ("Stop", None, "stop", 3600),
    ("UserPromptSubmit", None, "user-prompt-submit", 15),
]


def _hook_entry(matcher: str | None, sub_name: str, timeout: int) -> dict:
    entry: dict = {
        "hooks": [{
            "type": "command",
            "command": f"{HOOK_CMD_PREFIX} {sub_name}",
            "timeout": timeout,
        }]
    }
    if matcher:
        entry["matcher"] = matcher
    return entry


def _is_claugram_entry(entry: dict) -> bool:
    for h in entry.get("hooks", []):
        if str(h.get("command", "")).startswith(HOOK_CMD_PREFIX):
            return True
    return False


def build_hooks_block() -> dict:
    hooks: dict[str, list] = {}
    for event, matcher, sub_name, timeout in HOOK_SPECS:
        hooks.setdefault(event, []).append(_hook_entry(matcher, sub_name, timeout))
    return hooks


ENV_PREFIX = "CLAUGRAM_"


def patch_settings(project_root: Path, dry_run: bool = False,
                   extra_env: dict[str, str] | None = None) -> tuple[Path, dict]:
    path = paths.claude_settings_local_path(project_root)
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}

    hooks = data.setdefault("hooks", {})
    new_block = build_hooks_block()
    for event, entries in new_block.items():
        existing = hooks.setdefault(event, [])
        # drop any prior claugram entries for this event, then append fresh ones
        existing[:] = [e for e in existing if not _is_claugram_entry(e)]
        existing.extend(entries)

    # Auto-inject env vars so hooks/mcp-server pick up the project (and any
    # toggles) without the user exporting anything. Claude Code applies the
    # `env` block to the session, hook and MCP processes it spawns.
    env = data.setdefault("env", {})
    for key in list(env):
        if key.startswith(ENV_PREFIX):
            del env[key]
    env["CLAUGRAM_PROJECT"] = str(Path(project_root).resolve())
    for key, val in (extra_env or {}).items():
        env[key] = str(val)

    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path, data


def unpatch_settings(project_root: Path) -> Path | None:
    path = paths.claude_settings_local_path(project_root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    hooks = data.get("hooks", {})
    for event in list(hooks.keys()):
        hooks[event] = [e for e in hooks[event] if not _is_claugram_entry(e)]
        if not hooks[event]:
            del hooks[event]
    if not hooks:
        data.pop("hooks", None)

    env = data.get("env", {})
    for key in list(env):
        if key.startswith(ENV_PREFIX):
            del env[key]
    if not env:
        data.pop("env", None)

    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path
