"""Load project config and user credentials."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from . import paths
from .models import Config


class ConfigError(RuntimeError):
    pass


def load_config(project_root: Path) -> Config:
    path = paths.project_config_path(project_root)
    if not path.exists():
        raise ConfigError(
            f"No claugram config at {path}. Run `claugram init` in this project first."
        )
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return Config.from_dict(data)


def try_load_config(project_root: Path) -> Config | None:
    try:
        return load_config(project_root)
    except ConfigError:
        return None


def load_credentials() -> dict:
    path = paths.credentials_path()
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def resolve_bot_token(bot_token_ref: str) -> str | None:
    """Resolve a token reference to an actual token.

    Supported forms:
      env:VAR_NAME   -> read from environment variable
      user:<name>    -> read from user credentials.toml [tokens.<name>]
      raw:<token>    -> literal (discouraged; kept for tests)
    """
    if not bot_token_ref:
        return None
    if bot_token_ref.startswith("env:"):
        return os.environ.get(bot_token_ref[4:])
    if bot_token_ref.startswith("raw:"):
        return bot_token_ref[4:]
    if bot_token_ref.startswith("user:"):
        name = bot_token_ref[5:] or "default"
        creds = load_credentials()
        tokens = creds.get("tokens", {})
        entry = tokens.get(name)
        if isinstance(entry, dict):
            return entry.get("bot_token")
        return entry
    # fall back: treat as env var name for convenience
    return os.environ.get(bot_token_ref)
