"""Write project config and user credentials."""

from __future__ import annotations

from pathlib import Path

from . import paths, _toml
from .models import Config


def write_config(project_root: Path, config: Config) -> Path:
    cfg_dir = paths.project_config_dir(project_root)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = paths.project_config_path(project_root)
    path.write_text(_toml.dumps(config.to_dict()), encoding="utf-8")
    return path


def save_bot_token(name: str, bot_token: str) -> Path:
    """Persist a bot token under [tokens.<name>] in user credentials."""
    paths.ensure_user_dirs()
    cred_path = paths.credentials_path()

    existing = ""
    if cred_path.exists():
        existing = cred_path.read_text(encoding="utf-8")

    import tomllib
    data = tomllib.loads(existing) if existing.strip() else {}
    data.setdefault("tokens", {})[name] = {"bot_token": bot_token}

    cred_path.write_text(_toml.dumps(data), encoding="utf-8")
    try:  # best-effort tighten perms on POSIX
        cred_path.chmod(0o600)
    except OSError:
        pass
    return cred_path
