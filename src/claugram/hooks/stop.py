"""Stop hook: send a summary and optionally wait for a reply to continue.

Returning {"decision": "block", "reason": <text>} keeps Claude going and feeds
the user's reply back to it. Returning nothing lets Claude stop for real.
A per-session round counter plus stop_hook_active guard the against loops.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..runtime import Runtime
from ..telegram import formatting, approvals
from ..security import redact
from ..storage import audit_log
from .base import run_hook


def _last_assistant_text(transcript_path: str | None) -> str:
    if not transcript_path:
        return ""
    p = Path(transcript_path)
    if not p.exists():
        return ""
    last = ""
    try:
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "assistant" or obj.get("role") == "assistant":
                msg = obj.get("message", obj)
                content = msg.get("content")
                if isinstance(content, str):
                    last = content
                elif isinstance(content, list):
                    texts = [b.get("text", "") for b in content
                             if isinstance(b, dict) and b.get("type") == "text"]
                    if texts:
                        last = "\n".join(texts)
    except OSError:
        return ""
    return last.strip()[:1200]


def handle(event: dict, rt: Optional[Runtime]):
    if rt is None:
        return None
    import os
    if os.environ.get("CLAUGRAM_IN_CONTROLLER"):
        # Running inside a controller `claude -p`: never block here, or the
        # headless run would hang. The controller sends its own summary and
        # handles continuation via /continue.
        return None
    if not rt.forwarding_enabled():
        return None  # telegram off (schedule/env) -> let Claude stop normally

    session_id = event.get("session_id") or "default"
    stop_active = bool(event.get("stop_hook_active"))
    counter_key = f"stop_rounds:{session_id}"
    rounds = int(rt.store.kv_get(counter_key, "0") or "0")

    max_rounds = rt.config.approval.max_continue_rounds
    if rounds >= max_rounds:
        rt.store.kv_set(counter_key, "0")
        return None  # let it stop; avoid infinite continue loop

    chat_id = rt.primary_chat_id
    summary_text = _last_assistant_text(event.get("transcript_path")) \
        or "Claude finished this turn."
    text = formatting.summary(redact(summary_text), project=rt.config.project_name,
                              session=rt.session_label(session_id))

    timeout = rt.config.approval.stop_reply_timeout_sec
    qid = rt.store.create_question(rt.project_id, session_id, chat_id,
                                   summary_text, None, timeout)
    sent = rt.client.send_message(chat_id, text)
    rt.store.attach_question_message(qid, sent.get("message_id"))
    audit_log.record_event(rt.store, "stop_summary", {"session": session_id},
                           project_id=rt.project_id)

    row = rt.store.wait_for_question(qid, timeout)
    if row is None or row["status"] != "answered":
        rt.store.kv_set(counter_key, "0")
        return None  # timeout -> allow stop

    answer = (row["answer_text"] or "").strip()
    if answer.lower() in ("/done", "done", "stop"):
        rt.store.kv_set(counter_key, "0")
        return None  # user is satisfied -> allow stop

    rt.store.kv_set(counter_key, str(rounds + 1))
    return {"decision": "block", "reason": answer}


def main() -> None:
    run_hook(handle)


if __name__ == "__main__":
    main()
