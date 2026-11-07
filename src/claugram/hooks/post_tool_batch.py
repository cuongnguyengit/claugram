"""PostToolBatch hook: send a single rolled-up notification for a tool batch."""

from __future__ import annotations

from typing import Optional

from ..runtime import Runtime
from ..mcp import tools
from .base import run_hook

_QUIET = {"Read", "Grep", "Glob", "LS", "NotebookRead"}


def handle(event: dict, rt: Optional[Runtime]):
    if rt is None or not rt.config.notifications.notify_batch_summary:
        return None
    batch = event.get("tools") or event.get("batch") or []
    names = []
    for item in batch:
        name = (item.get("tool_name") or "").split("__")[-1]
        if name and name not in _QUIET:
            names.append(name)
    if not names:
        return None
    from collections import Counter
    counts = Counter(names)
    summary = ", ".join(f"{n}×{c}" for n, c in counts.items())
    tools.do_notify(rt, "Batch complete", summary, level="info",
                    session_id=event.get("session_id"))
    return None


def main() -> None:
    run_hook(handle)


if __name__ == "__main__":
    main()
