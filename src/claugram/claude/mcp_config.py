"""Generate the MCP config file Claude Code loads via --mcp-config."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import paths


def build_mcp_config(project_root: Path, server_name: str = "claugram") -> dict:
    root = str(Path(project_root).resolve())
    return {
        "mcpServers": {
            server_name: {
                "command": "claugram",
                "args": ["mcp-server", "--project", root],
                "env": {"CLAUGRAM_PROJECT": root},
            }
        }
    }


def write_mcp_config(project_root: Path, server_name: str = "claugram",
                     dry_run: bool = False) -> Path:
    path = paths.project_mcp_config_path(project_root)
    config = build_mcp_config(project_root, server_name)
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return path
