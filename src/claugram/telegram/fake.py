"""A file-backed fake Telegram transport for testing without a real bot.

It implements the same surface the code uses on ``TelegramClient``
(send_message, edit_message_reply_markup, answer_callback_query, get_updates,
get_me) but stores everything under a directory so that separate processes
(bot, mcp-server, hooks) share one channel — exactly like Telegram's servers
do for the real transport.

Layout (default ``<CLAUGRAM_HOME>/fake``):
  outbox.jsonl   append-only log of everything "sent" (for assertions)
  inbox.jsonl    updates queued by a test to simulate the human
  meta.json      {"message_id": N} counter
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional


class FakeTransport:
    def __init__(self, base_dir: Path):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)
        self.outbox = self.base / "outbox.jsonl"
        self.inbox = self.base / "inbox.jsonl"
        self.meta = self.base / "meta.json"

    # ----- internal -----
    def _next_message_id(self) -> int:
        data = {}
        if self.meta.exists():
            try:
                data = json.loads(self.meta.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        mid = int(data.get("message_id", 1000)) + 1
        data["message_id"] = mid
        self.meta.write_text(json.dumps(data), encoding="utf-8")
        return mid

    def _append(self, path: Path, obj: dict) -> None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")

    # ----- transport surface -----
    def get_me(self) -> dict:
        return {"username": "fake_bot", "id": 1}

    def send_message(self, chat_id: int, text: str, parse_mode: Optional[str] = None,
                     reply_markup: Optional[dict] = None,
                     disable_notification: bool = False) -> dict:
        mid = self._next_message_id()
        self._append(self.outbox, {
            "kind": "send", "message_id": mid, "chat_id": chat_id,
            "text": text, "reply_markup": reply_markup,
        })
        return {"message_id": mid}

    def edit_message_reply_markup(self, chat_id: int, message_id: int,
                                  reply_markup: Optional[dict] = None) -> dict:
        self._append(self.outbox, {
            "kind": "edit_markup", "chat_id": chat_id, "message_id": message_id,
            "reply_markup": reply_markup,
        })
        return {"message_id": message_id}

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> dict:
        self._append(self.outbox, {
            "kind": "answer_cb", "callback_query_id": callback_query_id, "text": text,
        })
        return {"ok": True}

    def set_my_commands(self, commands) -> dict:
        self._append(self.outbox, {"kind": "set_commands", "count": len(commands)})
        return {"ok": True}

    def get_updates(self, offset: Optional[int] = None, timeout: int = 30,
                    allowed_updates: Optional[list[str]] = None) -> list[dict]:
        updates = self._read_inbox()
        pending = [u for u in updates if offset is None or u["update_id"] >= offset]
        if not pending:
            time.sleep(0.2)  # avoid a hot loop; the fake never truly long-polls
        return pending

    def _read_inbox(self) -> list[dict]:
        if not self.inbox.exists():
            return []
        out = []
        for line in self.inbox.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return out


class FakeControl:
    """Test-side helper to drive a FakeTransport channel like a human would."""

    def __init__(self, base_dir: Path):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)
        self.transport = FakeTransport(self.base)
        self._uid = 0

    def _next_update_id(self) -> int:
        self._uid += 1
        return self._uid

    def push_text(self, chat_id: int, text: str,
                  reply_to_message_id: Optional[int] = None) -> None:
        msg: dict[str, Any] = {"message_id": 9000 + self._uid,
                               "chat": {"id": chat_id}, "text": text}
        if reply_to_message_id:
            msg["reply_to_message"] = {"message_id": reply_to_message_id}
        self.transport._append(self.transport.inbox,
                               {"update_id": self._next_update_id(), "message": msg})

    def push_callback(self, chat_id: int, data: str, message_id: int,
                      from_id: Optional[int] = None) -> None:
        cq = {"id": f"cb{self._uid}", "data": data, "from": {"id": from_id or chat_id},
              "message": {"chat": {"id": chat_id}, "message_id": message_id}}
        self.transport._append(self.transport.inbox,
                               {"update_id": self._next_update_id(), "callback_query": cq})

    def sent_messages(self) -> list[dict]:
        return [o for o in self._outbox() if o.get("kind") == "send"]

    def sent_texts(self) -> list[str]:
        return [o["text"] for o in self.sent_messages()]

    def _outbox(self) -> list[dict]:
        if not self.transport.outbox.exists():
            return []
        out = []
        for line in self.transport.outbox.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out
