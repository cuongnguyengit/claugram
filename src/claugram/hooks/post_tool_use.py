"""PostToolUse hook: notify Telegram after meaningful tool calls only."""

from __future__ import annotations

import re
from typing import Optional

from ..runtime import Runtime
from ..mcp import tools
from .base import run_hook

_TEST_RE = re.compile(r"\b(pytest|jest|vitest|npm (run )?test|tox|go test|cargo test|make (test|build|lint)|ruff|eslint|mypy|tsc)\b", re.I)


def handle(event: dict, rt: Optional[Runtime]):
    if rt is None:
        return None
    tool_name = (event.get("tool_name") or "").split("__")[-1]
    tool_input = event.get("tool_input") or {}
    tool_response = event.get("tool_response") or {}
    sid = event.get("session_id")
    notif = rt.config.notifications

    if tool_name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        if not notif.notify_post_edit:
            return None
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or "?"
        tools.do_notify(rt, "Edited file", str(path), level="success",
                        changed_files=[str(path)], session_id=sid)
        return None

    if tool_name == "Bash":
        if not notif.notify_post_bash:
            return None
        command = str(tool_input.get("command", ""))
        failed = _looks_failed(tool_response)
        is_test = bool(_TEST_RE.search(command))
        if failed:
            tools.do_notify(rt, "Command failed", command, level="error", session_id=sid)
        elif is_test:
            tools.do_notify(rt, "Command finished", command, level="success", session_id=sid)
        # ordinary bash commands are not notified individually
        return None

    # Read/Grep/Glob/LS etc. -> never notify individually
    return None


def _looks_failed(tool_response: dict) -> bool:
    if not isinstance(tool_response, dict):
        return False
    for key in ("returnCode", "return_code", "exit_code", "exitCode"):
        if key in tool_response:
            try:
                return int(tool_response[key]) != 0
            except (TypeError, ValueError):
                pass
    if tool_response.get("is_error") or tool_response.get("error"):
        return True
    return False


def main() -> None:
    run_hook(handle)


if __name__ == "__main__":
    main()
