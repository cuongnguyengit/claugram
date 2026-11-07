"""The Telegram update dispatcher — the single long-poller.

Only this process may call getUpdates. It correlates replies and inline-button
callbacks to pending questions/permissions in the shared store, and turns
slash-commands into controller jobs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .client import TelegramClient, TelegramError
from . import approvals
from .. import fileview
from ..security import redact
from ..storage import Store, audit_log

log = logging.getLogger("claugram.bot")

# (command, short description) — registered with Telegram via setMyCommands so
# the "/" autocomplete menu shows hints. Keep in sync with HELP_TEXT.
BOT_COMMANDS: list[tuple[str, str]] = [
    ("projects", "List registered projects"),
    ("use", "Switch active project: /use <n|name>"),
    ("code", "Run Claude on a task: /code <task>"),
    ("ask", "Ask Claude (read-mostly): /ask <question>"),
    ("continue", "Continue the last session: /continue <prompt>"),
    ("status", "Show current state"),
    ("diff", "Show git diff summary"),
    ("test", "Run the project tests"),
    ("sessions", "List Claude sessions"),
    ("session", "Pick a session: /session <n|id|name|none>"),
    ("name", "Name a session: /name <n|id> <name>"),
    ("ls", "List files: /ls [subdir]"),
    ("cat", "Show a file: /cat <file> [start-end]"),
    ("grep", "Search files: /grep <regex>"),
    ("tree", "Directory tree: /tree [subdir]"),
    ("approve", "Approve the pending permission"),
    ("deny", "Deny the pending permission"),
    ("done", "Let Claude stop"),
    ("help", "Show help"),
]

HELP_TEXT = (
    "Claugram commands:\n"
    "/projects — list registered projects\n"
    "/use <n|name> — switch active project for this chat\n"
    "/code <task> — run Claude on a task\n"
    "/ask <question> — ask Claude (read-mostly)\n"
    "/continue <prompt> — continue the last session\n"
    "/status — show current state\n"
    "/diff — show git diff summary\n"
    "/test — run the project tests\n"
    "/sessions — list Claude sessions in this project\n"
    "/session <n|id|name|none> — pick which session to resume\n"
    "/name <n|id> <name> — give a session a friendly name\n"
    "/ls [subdir] — list files · /cat <file> [start-end] — show a file\n"
    "/grep <regex> — search files · /tree [subdir] — directory tree\n"
    "   pipe: /cat app.py | grep def | head 20   (filters: grep, head, tail, nl, wc)\n"
    "/approve /deny — decide the pending permission\n"
    "/done — let Claude stop\n"
    "/help — this message\n\n"
    "You can also just reply to a question to answer it."
)

# Commands that become controller jobs: name -> (needs_prompt)
JOB_COMMANDS = {
    "code": True,
    "ask": True,
    "continue": True,
    "diff": False,
    "test": False,
}


@dataclass
class BotContext:
    store: Store
    client: TelegramClient
    allowed_chat_ids: set[int]
    # resolve the active project for a chat (None if none selected/registered)
    resolve_project: Callable[[int], Optional["ProjectRef"]]
    # select a project for a chat by name/index; returns the ref or None
    select_project: Callable[[int, str], Optional["ProjectRef"]]
    list_projects: Callable[[], list]
    # enqueue controller work for the chat's active project; None if no project
    enqueue: Callable[[str, str, int], Optional[str]]
    # per-chat status text
    status_provider: Callable[[int], str]


class BotPoller:
    def __init__(self, ctx: BotContext, poll_timeout: int = 30):
        self.ctx = ctx
        self.poll_timeout = poll_timeout
        self._running = False

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        self._running = True
        store = self.ctx.store
        offset_raw = store.kv_get("update_offset")
        offset = int(offset_raw) if offset_raw else None
        try:
            self.ctx.client.set_my_commands(BOT_COMMANDS)
        except Exception as exc:  # never fatal — menu hints are cosmetic
            log.warning("setMyCommands failed (menu hints unavailable): %s", exc)
        log.info("bot polling started")
        import time
        backoff = 3
        while self._running:
            try:
                updates = self.ctx.client.get_updates(
                    offset=offset, timeout=self.poll_timeout,
                    allowed_updates=["message", "edited_message", "callback_query"],
                )
                backoff = 3  # recovered
            except TelegramError as exc:
                log.warning("getUpdates error: %s", exc)
                time.sleep(3)
                continue
            except Exception as exc:
                # last-resort guard: no transient failure may kill the daemon.
                log.warning("getUpdates unexpected error (%s); retrying in %ds",
                            exc, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            for upd in updates:
                offset = upd["update_id"] + 1
                store.kv_set("update_offset", str(offset))
                try:
                    self._dispatch(upd)
                except Exception:  # never let one bad update kill the loop
                    log.exception("error handling update %s", upd.get("update_id"))

    # ----- dispatch -----
    def _dispatch(self, upd: dict) -> None:
        if "callback_query" in upd:
            self._handle_callback(upd["callback_query"])
            return
        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            return
        chat_id = msg.get("chat", {}).get("id")
        if chat_id is None:
            return
        if chat_id not in self.ctx.allowed_chat_ids:
            log.warning("ignoring message from unauthorized chat %s", chat_id)
            return
        text = (msg.get("text") or "").strip()
        if not text:
            return
        if text.startswith("/"):
            self._handle_command(chat_id, text, msg)
        else:
            self._handle_reply(chat_id, text, msg)

    # ----- commands -----
    def _handle_command(self, chat_id: int, text: str, msg: dict) -> None:
        parts = text[1:].split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]
        arg = parts[1].strip() if len(parts) > 1 else ""
        client = self.ctx.client

        if cmd in ("start", "help"):
            client.send_message(chat_id, HELP_TEXT)
            return
        if cmd == "projects":
            client.send_message(chat_id, self._list_projects(chat_id))
            return
        if cmd == "use":
            self._use_project(chat_id, arg)
            return
        if cmd == "status":
            client.send_message(chat_id, self.ctx.status_provider(chat_id))
            return
        if cmd == "sessions":
            client.send_message(chat_id, self._list_sessions(chat_id))
            return
        if cmd == "session":
            self._select_session(chat_id, arg)
            return
        if cmd == "name":
            self._name_session(chat_id, arg)
            return
        if cmd == "done":
            # answer the newest open question with the /done sentinel
            q = self.ctx.store.latest_open_question(chat_id)
            if q and self.ctx.store.answer_question(q["id"], "/done", chat_id):
                client.send_message(chat_id, "OK — letting Claude stop.")
            else:
                client.send_message(chat_id, "Nothing waiting to continue.")
            return
        if cmd in ("approve", "deny"):
            self._resolve_permission_command(chat_id, cmd)
            return
        if cmd in ("ls", "cat", "grep", "tree"):
            self._view_command(chat_id, cmd, arg)
            return
        if cmd in JOB_COMMANDS:
            needs_prompt = JOB_COMMANDS[cmd]
            if needs_prompt and not arg:
                client.send_message(chat_id, f"Usage: /{cmd} <text>")
                return
            ref = self.ctx.resolve_project(chat_id)
            if ref is None:
                client.send_message(chat_id,
                                    "No project selected. Use /projects then /use <name>.")
                return
            job_id = self.ctx.enqueue(cmd, arg, chat_id)
            client.send_message(chat_id, f"▶️ Queued /{cmd} on {ref.name}. Working…")
            audit_log.record_event(
                self.ctx.store, "controller_job_queued",
                {"command": cmd, "job_id": job_id}, project_id=ref.project_id)
            return
        client.send_message(chat_id, f"Unknown command /{cmd}. Try /help.")

    # ----- read-only project views (ls / cat / grep / tree) -----
    def _view_command(self, chat_id: int, cmd: str, arg: str) -> None:
        ref = self.ctx.resolve_project(chat_id)
        if ref is None:
            self.ctx.client.send_message(
                chat_id, "No project selected. Use /projects then /use <name>.")
            return
        root = ref.root
        full = f"{cmd} {arg}".strip()
        if "|" in full:
            # e.g. /cat app.py | grep def | head 20  — piping done in Python,
            # never a shell. Redact since a stage may surface file contents.
            out = redact(fileview.pipeline(root, full))
        elif cmd == "ls":
            out = fileview.ls(root, arg)
        elif cmd == "tree":
            out = fileview.tree(root, arg)
        elif cmd == "cat":
            path, _, rng = arg.partition(" ")
            # cat/grep can surface file contents -> redact secrets first
            out = redact(fileview.cat(root, path, rng))
        else:  # grep
            out = redact(fileview.grep(root, arg))
        self.ctx.client.send_message(chat_id, f"[{ref.name}] {out}")

    # ----- projects -----
    def _list_projects(self, chat_id: int) -> str:
        refs = self.ctx.list_projects()
        if not refs:
            return "No projects registered. Run `claugram init` in a repo first."
        active = self.ctx.resolve_project(chat_id)
        active_id = active.project_id if active else None
        lines = ["Registered projects:", ""]
        for i, r in enumerate(refs, 1):
            mark = " ⭐" if r.project_id == active_id else ""
            lines.append(f"{i}. {r.name}{mark}")
            lines.append(f"   {r.root}")
        lines += ["", "Use /use <n|name> to switch."]
        return "\n".join(lines)

    def _use_project(self, chat_id: int, arg: str) -> None:
        if not arg:
            self.ctx.client.send_message(chat_id, "Usage: /use <n|name>")
            return
        ref = self.ctx.select_project(chat_id, arg)
        if ref is None:
            self.ctx.client.send_message(
                chat_id, f"No project matched '{arg}'. Try /projects.")
            return
        self.ctx.client.send_message(chat_id, f"✅ Using {ref.name}\n{ref.root}")

    def _list_sessions(self, chat_id: int) -> str:
        from ..claude import sessions_disk
        ref = self.ctx.resolve_project(chat_id)
        if ref is None:
            return "No project selected. Use /projects then /use <name>."
        sessions = sessions_disk.list_sessions(ref.root, limit=10)
        if not sessions:
            return f"No Claude sessions found on disk for {ref.name} yet."
        store = self.ctx.store
        active = store.get_active_session(ref.project_id)
        lines = [f"Sessions in {ref.name}:", ""]
        for i, s in enumerate(sessions, 1):
            when = s.modified.astimezone().strftime("%m-%d %H:%M")
            mark = " ⭐" if s.session_id == active else ""
            name = store.get_session_name(s.session_id)
            head = s.short + (f" “{name}”" if name else "")
            lines.append(f"{i}. {head} · {when} · {s.message_count} msgs{mark}")
            lines.append(f"   {s.preview}")
        lines += ["", "Use /session <n|id|name> to select; /name <n|id> <name> to label."]
        return "\n".join(lines)

    def _resolve_session_ref(self, ref, arg: str):
        """Resolve a session by index/id (disk) or by a claugram-assigned name."""
        from ..claude import sessions_disk
        sid = sessions_disk.resolve_ref(ref.root, arg)
        if sid:
            return sid
        low = arg.strip().lower()
        for s in sessions_disk.list_sessions(ref.root, limit=50):
            name = self.ctx.store.get_session_name(s.session_id)
            if name and name.lower() == low:
                return s.session_id
        return None

    def _select_session(self, chat_id: int, arg: str) -> None:
        store = self.ctx.store
        ref = self.ctx.resolve_project(chat_id)
        if ref is None:
            self.ctx.client.send_message(
                chat_id, "No project selected. Use /projects then /use <name>.")
            return
        if not arg or arg.lower() in ("none", "clear", "off"):
            store.clear_active_session(ref.project_id)
            self.ctx.client.send_message(
                chat_id, "Cleared active session (will use most recent).")
            return
        sid = self._resolve_session_ref(ref, arg)
        if not sid:
            self.ctx.client.send_message(
                chat_id, f"No session matched '{arg}'. Try /sessions.")
            return
        store.set_active_session(ref.project_id, sid)
        label = store.get_session_name(sid) or sid[:8]
        self.ctx.client.send_message(
            chat_id, f"Active session set to {label}. Send /continue <prompt>.")

    def _name_session(self, chat_id: int, arg: str) -> None:
        ref = self.ctx.resolve_project(chat_id)
        if ref is None:
            self.ctx.client.send_message(
                chat_id, "No project selected. Use /projects then /use <name>.")
            return
        parts = arg.split(maxsplit=1)
        if len(parts) < 2:
            self.ctx.client.send_message(chat_id, "Usage: /name <n|id> <name>")
            return
        sref, name = parts[0], parts[1].strip()
        sid = self._resolve_session_ref(ref, sref)
        if not sid:
            self.ctx.client.send_message(
                chat_id, f"No session matched '{sref}'. Try /sessions.")
            return
        self.ctx.store.set_session_name(sid, name)
        self.ctx.client.send_message(chat_id, f"✅ Named {sid[:8]} → “{name}”.")

    def _resolve_permission_command(self, chat_id: int, cmd: str) -> None:
        store = self.ctx.store
        perm = store.latest_open_permission(chat_id)
        if not perm:
            self.ctx.client.send_message(chat_id, "No pending permission.")
            return
        decision = "allow" if cmd == "approve" else "deny"
        if store.decide_permission(perm["id"], decision, chat_id):
            self._clear_markup(chat_id, perm["telegram_message_id"])
            self.ctx.client.send_message(
                chat_id, f"{'✅ Allowed' if decision == 'allow' else '⛔ Denied'}.")

    # ----- replies (answers to questions) -----
    def _handle_reply(self, chat_id: int, text: str, msg: dict) -> None:
        store = self.ctx.store
        reply_to = msg.get("reply_to_message", {})
        target_mid = reply_to.get("message_id")

        # 1. explicit reply to a known question/permission message
        if target_mid:
            q = store.find_question_by_message(target_mid)
            if q and q["status"] == "pending":
                if store.answer_question(q["id"], text, chat_id):
                    self._clear_markup(chat_id, q["telegram_message_id"])
                    self.ctx.client.send_message(chat_id, "✅ Got it.")
                return
            p = store.find_permission_by_message(target_mid)
            if p and p["status"] == "pending":
                decision = "allow" if text.lower() in ("y", "yes", "allow", "ok") else "deny"
                store.decide_permission(p["id"], decision, chat_id, message=text)
                self._clear_markup(chat_id, p["telegram_message_id"])
                return

        # 2. plain text: how many things are waiting in this chat?
        questions = store.list_open_questions(chat_id)
        perms = store.list_open_permissions(chat_id)
        total = len(questions) + len(perms)

        if total > 1:
            # ambiguous across sessions/projects -> ask for a direct reply
            self.ctx.client.send_message(chat_id, self._pending_disambiguation(
                questions, perms))
            return

        if total == 1 and questions:
            q = questions[0]
            if store.answer_question(q["id"], text, chat_id):
                self._clear_markup(chat_id, q["telegram_message_id"])
                self.ctx.client.send_message(chat_id, "✅ Got it.")
            return

        if total == 1 and perms:
            p = perms[0]
            decision = "allow" if text.lower() in ("y", "yes", "allow", "ok") else "deny"
            store.decide_permission(p["id"], decision, chat_id, message=text)
            self._clear_markup(chat_id, p["telegram_message_id"])
            self.ctx.client.send_message(
                chat_id, f"{'✅ Allowed' if decision == 'allow' else '⛔ Denied'}.")
            return

        # 3. nothing pending -> treat as a /code task for convenience
        ref = self.ctx.resolve_project(chat_id)
        if ref is None:
            self.ctx.client.send_message(
                chat_id, "No project selected. Use /projects then /use <name>.")
            return
        self.ctx.enqueue("code", text, chat_id)
        self.ctx.client.send_message(chat_id, f"▶️ Queued as a task on {ref.name}. Working…")

    def _pending_disambiguation(self, questions: list, perms: list) -> str:
        lines = ["⚠️ Multiple things are waiting — reply directly to the one you mean:", ""]
        n = 1
        for q in questions:
            preview = (q["question"] or "").strip().splitlines()[0][:50] if q["question"] else "question"
            lines.append(f"{n}. {self._row_tag(q)} — {preview}")
            n += 1
        for p in perms:
            lines.append(f"{n}. {self._row_tag(p)} — permission: {p['tool_name']}")
            n += 1
        lines += ["", "Use the Telegram \"Reply\" action on the exact message."]
        return "\n".join(lines)

    def _row_tag(self, row) -> str:
        proj = self.ctx.store.get_project(row["project_id"])
        name = (proj["name"] if proj else None) or "project"
        sid = row["session_id"]
        return f"{name} · {sid[:8]}" if sid else name

    # ----- callbacks (inline buttons) -----
    def _handle_callback(self, cq: dict) -> None:
        data = cq.get("data", "")
        chat_id = cq.get("message", {}).get("chat", {}).get("id")
        msg_id = cq.get("message", {}).get("message_id")
        cq_id = cq.get("id")
        from_id = cq.get("from", {}).get("id")
        parsed = approvals.parse_callback(data)
        if not parsed or chat_id not in self.ctx.allowed_chat_ids:
            if cq_id:
                self.ctx.client.answer_callback_query(cq_id, "Ignored")
            return
        kind, short_id, value = parsed
        store = self.ctx.store
        if kind == "q":
            q = store.find_question_by_short(short_id)
            if q and q["status"] == "pending":
                import json
                options = json.loads(q["options_json"] or "[]")
                try:
                    answer = options[int(value)]
                except (ValueError, IndexError):
                    answer = value
                store.answer_question(q["id"], answer, from_id or chat_id)
                self._clear_markup(chat_id, msg_id)
                self.ctx.client.answer_callback_query(cq_id, f"Answered: {answer}")
                return
        elif kind == "p":
            p = store.find_permission_by_short(short_id)
            if p and p["status"] == "pending":
                store.decide_permission(p["id"], value, from_id or chat_id)
                self._clear_markup(chat_id, msg_id)
                self.ctx.client.answer_callback_query(
                    cq_id, "Allowed" if value == "allow" else "Denied")
                return
        self.ctx.client.answer_callback_query(cq_id, "Expired")

    def _clear_markup(self, chat_id: int, message_id: Optional[int]) -> None:
        if not message_id:
            return
        try:
            self.ctx.client.edit_message_reply_markup(chat_id, message_id, None)
        except TelegramError:
            pass
