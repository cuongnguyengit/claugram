"""Core MCP tool logic, independent of the MCP framework.

Each function sends a Telegram message and (for questions/permissions) blocks
polling the shared store until the bot records the human's answer. These are
synchronous; the server wraps the blocking ones in a worker thread.
"""

from __future__ import annotations

from typing import Any, Optional

from ..runtime import Runtime
from ..telegram import formatting, approvals
from ..security import redact
from ..storage import audit_log


def do_notify(rt: Runtime, title: str, message: str, level: str = "info",
              changed_files: Optional[list[str]] = None,
              session_id: Optional[str] = None) -> dict:
    if not rt.forwarding_enabled():
        return {"ok": True, "skipped": True, "reason": "telegram forwarding off"}
    text = formatting.notification(
        redact(title), redact(message), project=rt.config.project_name,
        level=level, changed_files=changed_files,
        session=rt.session_label(session_id),
    )
    result = rt.client.send_message(
        rt.primary_chat_id, text, parse_mode=None,
    )
    audit_log.record_event(rt.store, "notify_user",
                           {"title": title, "level": level},
                           project_id=rt.project_id)
    return {"ok": True, "telegram_message_id": result.get("message_id")}


def do_ask(rt: Runtime, question: str, context: str = "",
           options: Optional[list[str]] = None, allow_free_text: bool = True,
           timeout_sec: int = 86400, session_id: Optional[str] = None) -> dict:
    if not rt.forwarding_enabled():
        return {"answer": None, "muted": True, "raw_text": None,
                "answered_by": None, "timed_out": False}
    chat_id = rt.primary_chat_id
    qid = rt.store.create_question(
        rt.project_id, session_id, chat_id, question, options, timeout_sec)
    text = formatting.question(
        redact(question), redact(context), options,
        project=rt.config.project_name, allow_free_text=allow_free_text,
        session=rt.session_label(session_id))
    keyboard = approvals.question_keyboard(qid, options or [])
    sent = rt.client.send_message(chat_id, text, reply_markup=keyboard)
    rt.store.attach_question_message(qid, sent.get("message_id"))
    audit_log.record_event(rt.store, "ask_user_question",
                           {"question": question}, project_id=rt.project_id)

    row = rt.store.wait_for_question(qid, timeout_sec)
    if row is None or row["status"] != "answered":
        return {"answer": None, "timed_out": True,
                "raw_text": None, "answered_by": None}
    return {
        "answer": row["answer_text"],
        "raw_text": row["answer_text"],
        "answered_by": row["answered_by"],
        "answered_at": row["answered_at"],
        "timed_out": False,
    }


def do_request_permission(rt: Runtime, tool_name: str, tool_input: dict,
                          risk_level: str = "medium", reason: str = "",
                          options: Optional[list[str]] = None,
                          timeout_sec: Optional[int] = None,
                          session_id: Optional[str] = None) -> dict:
    if not rt.forwarding_enabled():
        return {"decision": rt.config.approval.default_on_timeout,
                "message": "telegram forwarding off; applied default", "muted": True}
    chat_id = rt.primary_chat_id
    timeout_sec = timeout_sec or rt.config.approval.permission_timeout_sec
    pid = rt.store.create_permission(
        rt.project_id, session_id, chat_id, tool_name, tool_input,
        risk_level, reason, timeout_sec)
    text = formatting.permission(
        tool_name, tool_input, risk_level, redact(reason),
        project=rt.config.project_name, session=rt.session_label(session_id))
    keyboard = approvals.permission_keyboard(pid, options)
    sent = rt.client.send_message(chat_id, redact(text), reply_markup=keyboard)
    rt.store.attach_permission_message(pid, sent.get("message_id"))
    audit_log.record_event(rt.store, "request_permission",
                           {"tool_name": tool_name, "risk": risk_level},
                           project_id=rt.project_id)

    row = rt.store.wait_for_permission(pid, timeout_sec)
    if row is None or row["status"] != "decided":
        default = rt.config.approval.default_on_timeout
        return {"decision": default, "message": "timed out; applied default",
                "timed_out": True}
    return {"decision": row["decision"], "message": row["reason"] or "",
            "timed_out": False}


def do_send_summary(rt: Runtime, summary: str,
                    changed_files: Optional[list[str]] = None,
                    tests: Optional[list[dict]] = None,
                    next_suggestion: str = "",
                    session_id: Optional[str] = None) -> dict:
    if not rt.forwarding_enabled():
        return {"ok": True, "skipped": True, "reason": "telegram forwarding off"}
    text = formatting.summary(
        redact(summary), changed_files, tests, redact(next_suggestion),
        project=rt.config.project_name, session=rt.session_label(session_id))
    result = rt.client.send_message(rt.primary_chat_id, text)
    audit_log.record_event(rt.store, "send_summary", {}, project_id=rt.project_id)
    return {"ok": True, "telegram_message_id": result.get("message_id")}


def do_get_pending_replies(rt: Runtime) -> dict:
    rt.store.expire_stale()
    questions = rt.store.conn.execute(
        "SELECT id, question, status, answer_text FROM pending_questions "
        "WHERE project_id=? ORDER BY created_at DESC LIMIT 10",
        (rt.project_id,)).fetchall()
    return {"questions": [dict(r) for r in questions]}
