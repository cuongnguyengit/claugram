"""Notification hook: forward Claude Code notifications to Telegram."""

from __future__ import annotations

from typing import Optional

from ..runtime import Runtime
from ..mcp import tools
from .base import run_hook


def handle(event: dict, rt: Optional[Runtime]):
    if rt is None:
        return None
    message = event.get("message") or event.get("notification") or "Claude needs attention."
    tools.do_notify(rt, "Attention", str(message), level="warning",
                    session_id=event.get("session_id"))
    return None


def main() -> None:
    run_hook(handle)


if __name__ == "__main__":
    main()
