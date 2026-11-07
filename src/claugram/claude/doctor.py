"""`claugram doctor` checks."""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

from .. import __version__
from ..config import paths, try_load_config, resolve_bot_token
from .cli import find_claude, claude_version
from .settings_patch import HOOK_CMD_PREFIX
from .claude_md_patch import BEGIN


@dataclass
class Check:
    label: str
    ok: bool
    detail: str = ""
    optional: bool = False  # optional checks warn but don't fail doctor


def run_checks(project_root: Path) -> list[Check]:
    checks: list[Check] = []

    # Python
    py = platform.python_version()
    checks.append(Check("Python version", sys.version_info >= (3, 11), py))

    # claugram
    checks.append(Check("claugram version", True, __version__))

    # claude CLI
    exe = find_claude()
    checks.append(Check("claude CLI found", exe is not None, exe or "not on PATH"))
    if exe:
        ver = claude_version()
        checks.append(Check("claude version", ver is not None, ver or "unknown"))

    # config
    config = try_load_config(project_root)
    checks.append(Check("claugram config", config is not None,
                        str(paths.project_config_path(project_root))))

    # Telegram token + getMe
    if config:
        token = resolve_bot_token(config.telegram.bot_token_ref)
        if token:
            try:
                from ..telegram import TelegramClient
                me = TelegramClient(token).get_me()
                checks.append(Check("Telegram token valid", True,
                                    f"@{me.get('username')}"))
            except Exception as exc:
                checks.append(Check("Telegram token valid", False, str(exc)))
        else:
            checks.append(Check("Telegram token valid", False,
                                f"unresolved: {config.telegram.bot_token_ref}"))
        checks.append(Check("chat_id allowed",
                            bool(config.telegram.allowed_chat_ids),
                            str(config.telegram.allowed_chat_ids)))

    # MCP importable
    try:
        import mcp.server.fastmcp  # noqa: F401
        checks.append(Check("MCP SDK importable", True, ""))
    except Exception as exc:
        checks.append(Check("MCP SDK importable", False, str(exc)))

    # settings.local.json
    sp = paths.claude_settings_local_path(project_root)
    if sp.exists():
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
            raw = json.dumps(data)
            checks.append(Check("Claude settings valid JSON",
                                HOOK_CMD_PREFIX in raw,
                                "claugram hooks present" if HOOK_CMD_PREFIX in raw
                                else "no claugram hooks"))
        except json.JSONDecodeError as exc:
            checks.append(Check("Claude settings valid JSON", False, str(exc)))
    else:
        checks.append(Check("Claude settings valid JSON", False, "file missing"))

    # CLAUDE.md managed block
    cmd = paths.claude_md_path(project_root)
    has_block = cmd.exists() and BEGIN in cmd.read_text(encoding="utf-8")
    checks.append(Check("CLAUDE.md managed block", has_block,
                        str(cmd) if has_block else "block missing"))

    # SQLite writable
    try:
        from ..storage import Store
        s = Store()
        s.kv_set("doctor_probe", "1")
        s.close()
        checks.append(Check("SQLite state writable", True, str(paths.state_db_path())))
    except Exception as exc:
        checks.append(Check("SQLite state writable", False, str(exc)))

    # Git repo (optional — claugram works without it)
    has_git = (project_root / ".git").exists()
    checks.append(Check("Git repo detected", has_git,
                        str(project_root / ".git") if has_git else "no git repo (optional)",
                        optional=True))

    return checks
