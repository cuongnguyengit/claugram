"""Append-only audit events."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .sqlite import Store


def record_event(
    store: Store,
    event_type: str,
    payload: dict[str, Any] | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
) -> str:
    eid = uuid.uuid4().hex
    store.conn.execute(
        "INSERT INTO audit_events(id, project_id, session_id, event_type, "
        "payload_json, created_at) VALUES(?,?,?,?,?,?)",
        (eid, project_id, session_id, event_type,
         json.dumps(payload or {}, default=str),
         datetime.now(timezone.utc).isoformat()),
    )
    store.conn.commit()
    return eid


def recent_events(store: Store, limit: int = 20) -> list:
    return store.conn.execute(
        "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
