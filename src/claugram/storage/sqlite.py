"""SQLite-backed shared state store.

This DB is the coordination bus between the four claugram processes:
the Telegram bot (the single long-poller), the MCP server, the hook
handlers, and the controller. The bot writes answers/decisions; MCP tools
and hooks insert pending rows and poll for the result.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from ..config import paths
from .migrations import apply_migrations


class _Result:
    """Materialized result of one execute() — fetches operate in memory, so no
    connection access happens outside the lock held during execute()."""

    __slots__ = ("_rows", "_it", "lastrowid", "rowcount")

    def __init__(self, rows: list, lastrowid: Any, rowcount: int):
        self._rows = rows
        self._it = iter(rows)
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self):
        return next(self._it, None)

    def fetchall(self):
        return list(self._it)

    def __iter__(self):
        return iter(self._rows)


class _SafeConn:
    """Serializes all access to a single sqlite3 connection with a lock.

    A single sqlite3.Connection is NOT safe for concurrent use across threads
    (check_same_thread=False only disables the guard). claugram shares one Store
    connection across threads — the MCP server runs each tool via
    asyncio.to_thread while others poll wait_for_* — so unserialized access
    intermittently corrupts the connection ("Cannot operate on a closed
    database" / OperationalError). Holding a lock across execute + result-drain
    makes every statement atomic.
    """

    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock):
        self._conn = conn
        self._lock = lock

    def execute(self, sql: str, params: tuple = ()) -> _Result:
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
            return _Result(rows, cur.lastrowid, cur.rowcount)

    def executescript(self, script: str) -> None:
        with self._lock:
            self._conn.executescript(script)

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @property
    def row_factory(self):
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._conn.row_factory = value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _future(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


class Store:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else paths.state_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        raw = sqlite3.connect(
            str(self.db_path), check_same_thread=False, timeout=30.0
        )
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA journal_mode=WAL")
        raw.execute("PRAGMA busy_timeout=30000")
        raw.execute("PRAGMA foreign_keys=ON")
        # all access goes through the lock-serialized wrapper (thread-safety)
        self.conn = _SafeConn(raw, self._lock)
        apply_migrations(self.conn)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ----- kv -----
    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def kv_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    # ----- projects -----
    def upsert_project(self, name: str, root_path: str) -> str:
        root_path = str(root_path)
        row = self.conn.execute(
            "SELECT id FROM projects WHERE root_path=?", (root_path,)
        ).fetchone()
        if row:
            self.conn.execute(
                "UPDATE projects SET name=? WHERE id=?", (name, row["id"])
            )
            self.conn.commit()
            return row["id"]
        pid = _new_id()
        self.conn.execute(
            "INSERT INTO projects(id, name, root_path, created_at) VALUES(?,?,?,?)",
            (pid, name, root_path, _now()),
        )
        self.conn.commit()
        return pid

    def get_project_by_root(self, root_path: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM projects WHERE root_path=?", (str(root_path),)
        ).fetchone()

    def get_project_by_name(self, name: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM projects WHERE name=?", (name,)
        ).fetchone()

    def list_projects(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM projects ORDER BY created_at"
        ).fetchall()

    def get_project(self, project_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()

    def set_active_project(self, chat_id: int, project_id: str) -> None:
        self.kv_set(f"active_project:{chat_id}", project_id)

    def get_active_project(self, chat_id: int) -> Optional[str]:
        return self.kv_get(f"active_project:{chat_id}")

    # ----- sessions -----
    def record_session(
        self, project_id: str, claude_session_id: str | None,
        transcript_path: str | None = None, status: str = "active",
    ) -> str:
        sid = _new_id()
        self.conn.execute(
            "INSERT INTO sessions(id, project_id, claude_session_id, "
            "last_transcript_path, last_activity_at, status) VALUES(?,?,?,?,?,?)",
            (sid, project_id, claude_session_id, transcript_path, _now(), status),
        )
        self.conn.commit()
        return sid

    def set_last_claude_session(self, project_id: str, claude_session_id: str) -> None:
        self.kv_set(f"last_session:{project_id}", claude_session_id)

    def get_last_claude_session(self, project_id: str) -> Optional[str]:
        return self.kv_get(f"last_session:{project_id}")

    def set_active_session(self, project_id: str, claude_session_id: str) -> None:
        self.kv_set(f"active_session:{project_id}", claude_session_id)

    def get_active_session(self, project_id: str) -> Optional[str]:
        return self.kv_get(f"active_session:{project_id}")

    def set_session_name(self, claude_session_id: str, name: str) -> None:
        self.kv_set(f"session_name:{claude_session_id}", name)

    def get_session_name(self, claude_session_id: str) -> Optional[str]:
        if not claude_session_id:
            return None
        return self.kv_get(f"session_name:{claude_session_id}")

    def clear_active_session(self, project_id: str) -> None:
        self.conn.execute("DELETE FROM kv WHERE key=?",
                          (f"active_session:{project_id}",))
        self.conn.commit()

    def touch_session(self, project_id: str, claude_session_id: str,
                      transcript_path: str | None = None) -> None:
        """Record/refresh a session row so we can list what claugram has seen."""
        row = self.conn.execute(
            "SELECT id FROM sessions WHERE project_id=? AND claude_session_id=?",
            (project_id, claude_session_id)).fetchone()
        if row:
            self.conn.execute(
                "UPDATE sessions SET last_activity_at=?, last_transcript_path=? "
                "WHERE id=?", (_now(), transcript_path, row["id"]))
        else:
            self.record_session(project_id, claude_session_id, transcript_path)
        self.conn.commit()

    # ----- pending questions -----
    def create_question(
        self, project_id: str, session_id: str | None, chat_id: int,
        question: str, options: list[str] | None, timeout_sec: int,
    ) -> str:
        qid = _new_id()
        self.conn.execute(
            "INSERT INTO pending_questions(id, project_id, session_id, chat_id, "
            "telegram_message_id, question, options_json, status, created_at, "
            "expires_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (qid, project_id, session_id, chat_id, None, question,
             json.dumps(options or []), "pending", _now(), _future(timeout_sec)),
        )
        self.conn.commit()
        return qid

    def attach_question_message(self, qid: str, message_id: int) -> None:
        self.conn.execute(
            "UPDATE pending_questions SET telegram_message_id=? WHERE id=?",
            (message_id, qid),
        )
        self.conn.commit()

    def get_question(self, qid: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM pending_questions WHERE id=?", (qid,)
        ).fetchone()

    def answer_question(self, qid: str, text: str, answered_by: int) -> bool:
        cur = self.conn.execute(
            "UPDATE pending_questions SET status='answered', answer_text=?, "
            "answered_by=?, answered_at=? WHERE id=? AND status='pending'",
            (text, answered_by, _now(), qid),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def latest_open_question(self, chat_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM pending_questions WHERE chat_id=? AND status='pending' "
            "ORDER BY created_at DESC LIMIT 1",
            (chat_id,),
        ).fetchone()

    def list_open_questions(self, chat_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM pending_questions WHERE chat_id=? AND status='pending' "
            "ORDER BY created_at DESC", (chat_id,),
        ).fetchall()

    def find_question_by_message(self, message_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM pending_questions WHERE telegram_message_id=?",
            (message_id,),
        ).fetchone()

    def find_question_by_short(self, short_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM pending_questions WHERE id LIKE ? "
            "ORDER BY created_at DESC LIMIT 1",
            (short_id + "%",),
        ).fetchone()

    # ----- pending permissions -----
    def create_permission(
        self, project_id: str, session_id: str | None, chat_id: int,
        tool_name: str, tool_input: dict, risk_level: str, reason: str,
        timeout_sec: int,
    ) -> str:
        pid = _new_id()
        self.conn.execute(
            "INSERT INTO pending_permissions(id, project_id, session_id, chat_id, "
            "telegram_message_id, tool_name, tool_input_json, risk_level, reason, "
            "status, created_at, expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, project_id, session_id, chat_id, None, tool_name,
             json.dumps(tool_input), risk_level, reason, "pending",
             _now(), _future(timeout_sec)),
        )
        self.conn.commit()
        return pid

    def attach_permission_message(self, pid: str, message_id: int) -> None:
        self.conn.execute(
            "UPDATE pending_permissions SET telegram_message_id=? WHERE id=?",
            (message_id, pid),
        )
        self.conn.commit()

    def get_permission(self, pid: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM pending_permissions WHERE id=?", (pid,)
        ).fetchone()

    def decide_permission(self, pid: str, decision: str, decided_by: int,
                          message: str | None = None) -> bool:
        cur = self.conn.execute(
            "UPDATE pending_permissions SET status='decided', decision=?, "
            "decided_by=?, decided_at=?, reason=COALESCE(?, reason) "
            "WHERE id=? AND status='pending'",
            (decision, decided_by, _now(), message, pid),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def latest_open_permission(self, chat_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM pending_permissions WHERE chat_id=? AND status='pending' "
            "ORDER BY created_at DESC LIMIT 1",
            (chat_id,),
        ).fetchone()

    def list_open_permissions(self, chat_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM pending_permissions WHERE chat_id=? AND status='pending' "
            "ORDER BY created_at DESC", (chat_id,),
        ).fetchall()

    def find_permission_by_message(self, message_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM pending_permissions WHERE telegram_message_id=?",
            (message_id,),
        ).fetchone()

    def find_permission_by_short(self, short_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM pending_permissions WHERE id LIKE ? "
            "ORDER BY created_at DESC LIMIT 1",
            (short_id + "%",),
        ).fetchone()

    # ----- controller jobs -----
    def enqueue_job(self, project_id: str | None, chat_id: int, command: str,
                    prompt: str) -> str:
        jid = _new_id()
        now = _now()
        self.conn.execute(
            "INSERT INTO controller_jobs(id, project_id, chat_id, command, prompt, "
            "status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (jid, project_id, chat_id, command, prompt, "queued", now, now),
        )
        self.conn.commit()
        return jid

    def claim_next_job(self) -> Optional[sqlite3.Row]:
        row = self.conn.execute(
            "SELECT * FROM controller_jobs WHERE status='queued' "
            "ORDER BY created_at LIMIT 1"
        ).fetchone()
        if not row:
            return None
        cur = self.conn.execute(
            "UPDATE controller_jobs SET status='running', updated_at=? "
            "WHERE id=? AND status='queued'",
            (_now(), row["id"]),
        )
        self.conn.commit()
        if cur.rowcount == 0:
            return None
        return row

    def finish_job(self, jid: str, status: str, result: str) -> None:
        self.conn.execute(
            "UPDATE controller_jobs SET status=?, result=?, updated_at=? WHERE id=?",
            (status, result[:8000], _now(), jid),
        )
        self.conn.commit()

    # ----- expiry sweep -----
    def expire_stale(self) -> None:
        now = _now()
        self.conn.execute(
            "UPDATE pending_questions SET status='expired' "
            "WHERE status='pending' AND expires_at < ?", (now,))
        self.conn.execute(
            "UPDATE pending_permissions SET status='expired' "
            "WHERE status='pending' AND expires_at < ?", (now,))
        self.conn.commit()

    # ----- polling helpers (used by MCP tools / hooks) -----
    def wait_for_question(self, qid: str, timeout_sec: int,
                          poll_interval: float = 1.0) -> Optional[sqlite3.Row]:
        deadline = time.monotonic() + timeout_sec
        while True:
            row = self.get_question(qid)
            if row and row["status"] != "pending":
                return row
            if row is None:
                return None
            if time.monotonic() >= deadline:
                return self.get_question(qid)
            time.sleep(poll_interval)

    def wait_for_permission(self, pid: str, timeout_sec: int,
                            poll_interval: float = 1.0) -> Optional[sqlite3.Row]:
        deadline = time.monotonic() + timeout_sec
        while True:
            row = self.get_permission(pid)
            if row and row["status"] != "pending":
                return row
            if row is None:
                return None
            if time.monotonic() >= deadline:
                return self.get_permission(pid)
            time.sleep(poll_interval)
