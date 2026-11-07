"""Discover Claude Code sessions on disk for a project.

Claude Code stores each session as a JSONL transcript at
    ~/.claude/projects/<slug>/<session-uuid>.jsonl
where <slug> is the absolute project path with every non-alphanumeric
character replaced by '-'. This lets us list and resume sessions that were
created before claugram was installed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone


def projects_root() -> Path:
    return Path.home() / ".claude" / "projects"


def slug_for(project_root: Path) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "-", str(Path(project_root).resolve()))


def session_dir(project_root: Path) -> Path | None:
    """Find the on-disk transcript dir, tolerant of drive-letter case."""
    root = projects_root()
    slug = slug_for(project_root)
    exact = root / slug
    if exact.is_dir():
        return exact
    if not root.is_dir():
        return None
    target = slug.lower()
    for child in root.iterdir():
        if child.is_dir() and child.name.lower() == target:
            return child
    return None


@dataclass
class SessionInfo:
    session_id: str
    modified: datetime
    preview: str
    message_count: int

    @property
    def short(self) -> str:
        return self.session_id[:8]


def _first_user_text(path: Path) -> tuple[str, int]:
    """Return (first real user prompt preview, message count)."""
    preview = ""
    count = 0
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") in ("user", "assistant"):
                count += 1
            if preview or obj.get("type") != "user":
                continue
            msg = obj.get("message", {})
            content = msg.get("content")
            text = content if isinstance(content, str) else ""
            if isinstance(content, list):
                text = " ".join(b.get("text", "") for b in content
                                 if isinstance(b, dict) and b.get("type") == "text")
            text = text.strip()
            # skip Claude's injected command/caveat wrappers
            if text and not text.startswith("<"):
                preview = text[:80]
    except OSError:
        pass
    return preview, count


def list_sessions(project_root: Path, limit: int = 10) -> list[SessionInfo]:
    d = session_dir(project_root)
    if not d:
        return []
    files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[SessionInfo] = []
    for f in files[:limit]:
        preview, count = _first_user_text(f)
        out.append(SessionInfo(
            session_id=f.stem,
            modified=datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc),
            preview=preview or "(no prompt captured)",
            message_count=count,
        ))
    return out


def resolve_ref(project_root: Path, ref: str) -> str | None:
    """Resolve a user-supplied reference to a full session id.

    Accepts a 1-based index into the recent list, a short id prefix, or a full
    uuid.
    """
    ref = ref.strip()
    sessions = list_sessions(project_root, limit=50)
    if ref.isdigit():
        idx = int(ref) - 1
        if 0 <= idx < len(sessions):
            return sessions[idx].session_id
        return None
    for s in sessions:
        if s.session_id == ref or s.session_id.startswith(ref):
            return s.session_id
    return None
