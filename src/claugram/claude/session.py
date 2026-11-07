"""Resolve which Claude session to resume for a controller job."""

from __future__ import annotations

from ..storage import Store


def resolve_session(store: Store, project_id: str, command: str) -> dict:
    """Decide how to invoke claude for a controller command.

    Precedence:
      1. A session explicitly selected via /session -> --resume <id>.
      2. /continue -> resume the remembered last session by id (or --continue
         if none is remembered but a conversation exists in the dir).
      3. /code, /ask, /test -> start a FRESH session, so each task is its own
         session (this is what makes /sessions show distinct entries).
    """
    active = store.get_active_session(project_id)
    if active:
        return {"session_id": active, "continue_last": False}

    if command == "continue":
        last = store.get_last_claude_session(project_id)
        if last:
            return {"session_id": last, "continue_last": False}
        return {"session_id": None, "continue_last": True}

    return {"session_id": None, "continue_last": False}


def remember_session(store: Store, project_id: str, session_id: str | None) -> None:
    if session_id:
        store.set_last_claude_session(project_id, session_id)
        store.touch_session(project_id, session_id)
