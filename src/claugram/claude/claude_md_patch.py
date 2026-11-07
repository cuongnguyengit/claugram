"""Insert/update/remove the claugram managed block in CLAUDE.md."""

from __future__ import annotations

import re
from pathlib import Path

from ..config import paths

BEGIN = "<!-- CLaugram:BEGIN -->"
END = "<!-- CLaugram:END -->"

_BLOCK_BODY = """
## Claugram Telegram human-in-the-loop

You can communicate with the user through the `claugram` MCP server.

IMPORTANT — asking questions: ALWAYS use `mcp__claugram__ask_user_question` to
ask the user anything, including multiple-choice. NEVER use the built-in
`AskUserQuestion` tool: it renders only in the local terminal, so a remote user
can neither see the options nor answer it — the session will hang. Only the
claugram MCP tool reaches Telegram and returns the chosen answer.

Use `mcp__claugram__ask_user_question` when:
- A decision affects product behavior, architecture, data deletion, deployment, credentials, or irreversible changes.
- Requirements are ambiguous and continuing would likely produce the wrong implementation.
- You need user input and the user may not be watching the local terminal.

Use `mcp__claugram__notify_user` when:
- You complete a meaningful milestone.
- You modify files.
- A test, build, or lint command finishes.
- You are blocked or need attention.

Do not ask after every small step.
Do not ask for confirmation for safe read-only exploration.
Prefer concise Telegram messages.
Before stopping after meaningful work, send a short summary through Telegram.

Risky actions require explicit approval:
- git push, deploy, release, publish
- deleting files or directories
- modifying credentials, secrets, `.env`, CI/CD, production config
- installing packages or running network scripts
- writing outside the current project root

If Telegram approval is denied, explain the denial and choose a safer local-only alternative.
"""


def managed_block() -> str:
    return f"{BEGIN}\n{_BLOCK_BODY.strip()}\n{END}\n"


def patch_claude_md(project_root: Path, dry_run: bool = False) -> Path:
    path = paths.claude_md_path(project_root)
    block = managed_block()
    if path.exists():
        content = path.read_text(encoding="utf-8")
        pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?",
                             re.DOTALL)
        if pattern.search(content):
            content = pattern.sub(block, content)
        else:
            sep = "" if content.endswith("\n") else "\n"
            content = content + sep + "\n" + block
    else:
        content = "# Project\n\n" + block
    if not dry_run:
        path.write_text(content, encoding="utf-8")
    return path


def unpatch_claude_md(project_root: Path) -> Path | None:
    path = paths.claude_md_path(project_root)
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8")
    pattern = re.compile(r"\n*" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?",
                         re.DOTALL)
    new = pattern.sub("\n", content)
    path.write_text(new, encoding="utf-8")
    return path
