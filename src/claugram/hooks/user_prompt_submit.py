"""UserPromptSubmit hook: audit the prompt (and note controller-injected ones)."""

from __future__ import annotations

from typing import Optional

from ..runtime import Runtime
from ..storage import audit_log
from .base import run_hook


def handle(event: dict, rt: Optional[Runtime]):
    if rt is None:
        return None
    prompt = event.get("prompt") or event.get("user_prompt") or ""
    audit_log.record_event(
        rt.store, "user_prompt_submit",
        {"prompt_preview": str(prompt)[:200]},
        project_id=rt.project_id,
        session_id=event.get("session_id"))
    return None


def main() -> None:
    run_hook(handle)


if __name__ == "__main__":
    main()
