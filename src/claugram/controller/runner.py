"""Execute controller jobs: run Claude headless and stream a summary back."""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path

from ..runtime import Runtime
from ..claude import cli as claude_cli
from ..claude import session as claude_session
from ..claude.mcp_config import write_mcp_config
from ..config import paths
from ..security import redact
from ..storage import audit_log
from ..telegram import formatting

log = logging.getLogger("claugram.controller")

_HEARTBEAT_INTERVAL = 30.0  # seconds between "still working…" pings during a run


def run_job(rt: Runtime, job) -> str:
    command = job["command"]
    prompt = job["prompt"] or ""
    chat_id = job["chat_id"]

    if command == "diff":
        return _handle_diff(rt, chat_id)
    if command == "test":
        prompt = "Run the project's test suite and report a concise pass/fail summary."
        command = "code"
    return _handle_claude(rt, chat_id, command, prompt)


def _handle_diff(rt: Runtime, chat_id: int) -> str:
    try:
        out = subprocess.run(
            ["git", "diff", "--stat"], cwd=str(rt.project_root),
            capture_output=True, text=True, timeout=30)
        text = out.stdout.strip() or "(no changes)"
    except (subprocess.SubprocessError, OSError) as exc:
        text = f"git diff failed: {exc}"
    rt.send(chat_id, f"📊 {rt.config.project_name} — git diff --stat\n\n{text}")
    return text


def _handle_claude(rt: Runtime, chat_id: int, command: str, prompt: str) -> str:
    mcp_path = None
    if rt.config.controller.attach_mcp:
        p = paths.project_mcp_config_path(rt.project_root)
        if not p.exists():
            write_mcp_config(rt.project_root, rt.config.claude.mcp_server_name)
        mcp_path = str(p)

    sess = claude_session.resolve_session(rt.store, rt.project_id, command)
    if command == "ask":
        permission_mode = "plan"  # read-mostly
    else:
        # /code and /continue default to acceptEdits so file edits are
        # auto-accepted and a headless run never stalls on an interactive edit
        # prompt. Risky tools (bash, deletes, …) still route to Telegram via the
        # permission hook regardless of this mode. Override per project via
        # [claude] default_permission_mode (plan, bypassPermissions, …); the
        # legacy "default"/empty value is treated as acceptEdits.
        permission_mode = rt.config.claude.default_permission_mode or "acceptEdits"
        if permission_mode == "default":
            permission_mode = "acceptEdits"

    audit_log.record_event(rt.store, "controller_run",
                           {"command": command, "prompt": prompt[:200]},
                           project_id=rt.project_id)

    session_id = None
    tool_uses = 0
    final_text = ""
    error_text = ""
    holder = {"sid": sess["session_id"]}

    # tell the user immediately, then heartbeat while Claude thinks (a heavy
    # resume can spend minutes in a single turn with no streamed events).
    resuming = "resuming" if (sess["session_id"] or sess["continue_last"]) else "starting"
    proj = rt.config.project_name
    rt.send(chat_id, f"▶️ {formatting.tag(proj, rt.session_label(holder['sid']))} — {resuming}…")

    stop_hb = threading.Event()

    def _heartbeat():
        while not stop_hb.wait(_HEARTBEAT_INTERVAL):
            rt.send(chat_id,
                    f"⏳ {formatting.tag(proj, rt.session_label(holder['sid']))} — still working…")

    hb = threading.Thread(target=_heartbeat, daemon=True)
    hb.start()

    try:
        for event in claude_cli.stream_headless(
            rt.project_root, prompt,
            session_id=sess["session_id"],
            continue_last=sess["continue_last"],
            mcp_config=mcp_path,
            permission_mode=permission_mode,
            max_turns=rt.config.controller.max_turns,
            idle_timeout_sec=rt.config.controller.idle_timeout_sec,
        ):
            etype = event.get("type")
            if etype == "system" and event.get("session_id"):
                session_id = event["session_id"]
                holder["sid"] = session_id
            elif etype == "assistant":
                tool_uses += _count_tool_uses(event)
            elif etype == "result":
                session_id = event.get("session_id", session_id)
                final_text = event.get("result") or event.get("text") or ""
            elif etype == "error":
                error_text += event.get("text", "") + "\n"
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("controller run failed")
        error_text += str(exc)
    finally:
        stop_hb.set()

    claude_session.remember_session(rt.store, rt.project_id, session_id)

    label = formatting.tag(proj, rt.session_label(session_id))
    if error_text.strip():
        rt.send(chat_id, f"❌ {label} — Claude error:\n{redact(error_text.strip()[:1500])}")
        return error_text

    body = final_text.strip() or "(no textual result)"
    calls = f" ({tool_uses} tool calls)" if tool_uses else ""
    footer = f"↩︎ Reply to continue · /session {session_id[:8]}" if session_id \
        else "↩︎ Reply to continue, or /done."
    rt.send(chat_id, f"✅ {label} — Done{calls}\n\n{redact(body[:3500])}\n\n{footer}")
    return body


def _count_tool_uses(event: dict) -> int:
    msg = event.get("message", {})
    content = msg.get("content", [])
    if not isinstance(content, list):
        return 0
    return sum(1 for b in content if isinstance(b, dict) and b.get("type") == "tool_use")
