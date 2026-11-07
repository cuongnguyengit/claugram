"""Platform-aware paths for user-level and project-level config/state."""

from __future__ import annotations

import os
from pathlib import Path


def user_config_dir() -> Path:
    """User-level config directory.

    Windows:  %APPDATA%\\claugram
    Linux/mac: $XDG_CONFIG_HOME/claugram or ~/.config/claugram
    """
    override = os.environ.get("CLAUGRAM_HOME")
    if override:
        return Path(override)

    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "claugram"

    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "claugram"


def credentials_path() -> Path:
    return user_config_dir() / "credentials.toml"


def state_db_path() -> Path:
    return user_config_dir() / "state.sqlite3"


def logs_dir() -> Path:
    return user_config_dir() / "logs"


def approvals_dir() -> Path:
    return user_config_dir() / "approvals"


def ensure_user_dirs() -> Path:
    root = user_config_dir()
    root.mkdir(parents=True, exist_ok=True)
    logs_dir().mkdir(parents=True, exist_ok=True)
    approvals_dir().mkdir(parents=True, exist_ok=True)
    return root


# ----- project level -----

def project_config_dir(project_root: Path) -> Path:
    return Path(project_root) / ".claugram"


def project_config_path(project_root: Path) -> Path:
    return project_config_dir(project_root) / "config.toml"


def project_mcp_config_path(project_root: Path) -> Path:
    return project_config_dir(project_root) / "mcp.claugram.json"


def claude_settings_local_path(project_root: Path) -> Path:
    return Path(project_root) / ".claude" / "settings.local.json"


def claude_md_path(project_root: Path) -> Path:
    return Path(project_root) / "CLAUDE.md"


def detect_project_root(start: Path | None = None) -> Path:
    """Walk up from *start* looking for a project marker; fall back to cwd."""
    start = Path(start or Path.cwd()).resolve()
    markers = (".git", ".claugram", "pyproject.toml", "package.json")
    for candidate in (start, *start.parents):
        for marker in markers:
            if (candidate / marker).exists():
                return candidate
    return start
