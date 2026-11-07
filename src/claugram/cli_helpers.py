"""Small shared helpers for CLI output (status)."""

from __future__ import annotations

from .runtime import Runtime


def status_lines(rt: Runtime) -> list[str]:
    store = rt.store
    store.expire_stale()
    pending_q = store.conn.execute(
        "SELECT COUNT(*) c FROM pending_questions WHERE project_id=? AND status='pending'",
        (rt.project_id,)).fetchone()["c"]
    pending_p = store.conn.execute(
        "SELECT COUNT(*) c FROM pending_permissions WHERE project_id=? AND status='pending'",
        (rt.project_id,)).fetchone()["c"]
    last = store.conn.execute(
        "SELECT created_at FROM audit_events WHERE project_id=? "
        "ORDER BY created_at DESC LIMIT 1", (rt.project_id,)).fetchone()
    last_session = store.get_last_claude_session(rt.project_id) or "-"
    active = store.get_active_session(rt.project_id)
    from .schedule import forwarding_status
    return [
        f"Project: {rt.project_root}",
        f"Telegram chats: {sorted(rt.allowed_chat_ids)}",
        f"Telegram forwarding: {forwarding_status(rt.config)}",
        f"Active session: {active[:8] if active else '(most recent)'}",
        f"Last Claude session: {last_session[:8] if last_session != '-' else '-'}",
        f"Pending approvals: {pending_p}",
        f"Pending questions: {pending_q}",
        f"Last activity: {last['created_at'] if last else '-'}",
    ]
