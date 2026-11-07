"""FastMCP server exposing claugram tools to Claude Code.

Launched by Claude Code via `claugram mcp-server --project <path>` (see the
generated .claugram/mcp.claugram.json). Communicates over stdio JSON-RPC.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Optional

from ..runtime import Runtime, setup_logging
from . import tools


def build_server(project_root: Path):
    from mcp.server.fastmcp import FastMCP

    rt = Runtime(project_root)
    mcp = FastMCP(rt.config.claude.mcp_server_name or "claugram")

    @mcp.tool()
    async def notify_user(
        title: str,
        message: str = "",
        level: str = "info",
        session_id: str = "",
        project: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Send a one-way notification to the user's Telegram (no reply awaited).

        Use for milestones, file changes, finished tests/builds, or when blocked.
        """
        changed = (metadata or {}).get("changed_files")
        return await asyncio.to_thread(
            tools.do_notify, rt, title, message, level, changed,
            session_id or None)

    @mcp.tool()
    async def ask_user_question(
        question: str,
        context: str = "",
        options: Optional[list[str]] = None,
        allow_free_text: bool = True,
        timeout_sec: int = 86400,
        default: Optional[str] = None,
    ) -> dict:
        """Ask the user a question via Telegram and wait for their answer.

        Use when a decision affects behavior, architecture, data, deployment or
        credentials, or when requirements are ambiguous and the user may not be
        watching the local terminal.
        """
        return await asyncio.to_thread(
            tools.do_ask, rt, question, context, options,
            allow_free_text, timeout_sec)

    @mcp.tool()
    async def request_permission(
        tool_name: str,
        tool_input: dict[str, Any],
        risk_level: str = "medium",
        reason: str = "",
        options: Optional[list[str]] = None,
    ) -> dict:
        """Ask the user to approve or deny a risky action via Telegram."""
        return await asyncio.to_thread(
            tools.do_request_permission, rt, tool_name, tool_input,
            risk_level, reason, options)

    @mcp.tool()
    async def send_summary(
        summary: str,
        changed_files: Optional[list[str]] = None,
        tests: Optional[list[dict]] = None,
        next_suggestion: str = "",
    ) -> dict:
        """Send an end-of-phase summary to Telegram."""
        return await asyncio.to_thread(
            tools.do_send_summary, rt, summary, changed_files,
            tests, next_suggestion)

    @mcp.tool()
    async def get_pending_replies() -> dict:
        """List recent questions and whether they have been answered."""
        return await asyncio.to_thread(tools.do_get_pending_replies, rt)

    return mcp


def main(project_root: Optional[Path] = None) -> None:
    setup_logging("mcp")
    root = project_root or Path(os.environ.get("CLAUGRAM_PROJECT", Path.cwd()))
    server = build_server(Path(root))
    server.run()


if __name__ == "__main__":
    main()
