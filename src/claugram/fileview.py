"""Read-only project inspection for the Telegram bot: ls / cat / grep / tree,
plus safe `|` pipelines (grep/head/tail/nl/wc) implemented in Python — no shell.

Pure functions (stdlib only) returning ready-to-send text. No shell is invoked,
paths are confined to the project root (traversal-safe), and output is capped so
a reply always fits in a Telegram message. Callers should still redact() the
output of `cat`/`grep`/`pipeline` since files may contain secrets.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# directories that are noise for remote inspection
_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".mypy_cache", ".pytest_cache", ".idea", ".tox", "dist", "build",
    ".next", ".cache", ".gradle", "target", ".claugram",
}
_MAX_CHARS = 3500          # keep well under Telegram's 4096 limit
_MAX_FILE_BYTES = 2_000_000
_MAX_GREP_HITS = 60

_SOURCES = ("ls", "cat", "grep", "tree")
_FILTERS = ("grep", "head", "tail", "nl", "wc")


class ViewError(Exception):
    """A user-facing message explaining why a view could not be produced."""


def _human(n: float) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


def _safe(root: Path | str, sub: str) -> Path:
    """Resolve `sub` under `root`; raise ViewError if it escapes the root."""
    base = Path(root).resolve()
    target = (base / sub).resolve() if sub else base
    try:
        target.relative_to(base)
    except ValueError:
        raise ViewError(f"⛔ Path escapes project root: {sub}")
    return target


def _cap(text: str) -> str:
    if len(text) <= _MAX_CHARS:
        return text
    return text[:_MAX_CHARS] + f"\n… (truncated; {len(text)} chars total)"


def _unquote(s: str) -> str:
    """Strip one pair of matching surrounding quotes (shell habit: grep 'x y')."""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


# --------------------------------------------------------------------------- #
# line-producing cores: return (header, lines); raise ViewError on failure
# --------------------------------------------------------------------------- #
def _ls_lines(root, sub: str = "") -> tuple[str, list[str]]:
    target = _safe(root, sub)
    if not target.exists():
        raise ViewError(f"Not found: {sub or '.'}")
    base = Path(root).resolve()
    if target.is_file():
        return f"📄 {target.relative_to(base)}  ({_human(target.stat().st_size)})", []
    lines = []
    for p in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if p.is_dir():
            lines.append(f"{p.name}/" + ("  …" if p.name in _SKIP_DIRS else ""))
        else:
            try:
                lines.append(f"{p.name}  {_human(p.stat().st_size)}")
            except OSError:
                lines.append(p.name)
    rel = target.relative_to(base)
    head = f"📁 {rel}" if str(rel) != "." else f"📁 {base.name} (root)"
    return head, lines


def _cat_lines(root, sub: str, rng: str = "") -> tuple[str, list[str]]:
    sub = _unquote(sub)
    if not sub:
        raise ViewError("Usage: /cat <file> [start-end]")
    target = _safe(root, sub)
    if not target.exists() or not target.is_file():
        raise ViewError(f"Not a file: {sub}")
    size = target.stat().st_size
    if size > _MAX_FILE_BYTES:
        raise ViewError(f"File too large to show ({_human(size)}). "
                        "Use /grep or a line range.")
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ViewError(f"Cannot read {sub}: {exc}")
    all_lines = text.splitlines()
    total = len(all_lines)
    start, end = 1, total
    if rng:
        m = re.match(r"^(\d+)(?:-(\d+))?$", rng.strip())
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else start
    start = max(1, start)
    end = min(total, end) if total else 0
    body = [f"{i}\t{ln}" for i, ln in enumerate(all_lines[start - 1:end], start)]
    return f"📄 {sub}  (lines {start}-{end} of {total})", body


def _grep_lines(root, pattern: str, max_hits: int = _MAX_GREP_HITS) -> tuple[str, list[str]]:
    pattern = _unquote(pattern)
    if not pattern:
        raise ViewError("Usage: /grep <regex>   (case-insensitive, text files)")
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ViewError(f"Bad regex: {exc}")
    base = Path(root).resolve()
    hits: list[str] = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            fp = Path(dirpath) / fn
            try:
                if fp.stat().st_size > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            scanned += 1
            try:
                with fp.open("r", encoding="utf-8", errors="ignore") as f:
                    for ln, line in enumerate(f, 1):
                        if rx.search(line):
                            rel = fp.relative_to(base)
                            hits.append(f"{rel}:{ln}: {line.strip()[:200]}")
                            if len(hits) >= max_hits:
                                break
            except OSError:
                continue
            if len(hits) >= max_hits:
                break
        if len(hits) >= max_hits:
            break
    if not hits:
        raise ViewError(f"No matches for /{pattern}/ (scanned {scanned} files).")
    capped = " (capped)" if len(hits) >= max_hits else ""
    return f"🔎 {len(hits)} match(es) for /{pattern}/{capped}:", hits


def _tree_lines(root, sub: str = "", max_depth: int = 2) -> tuple[str, list[str]]:
    target = _safe(root, sub)
    if not target.exists() or not target.is_dir():
        raise ViewError(f"Not a directory: {sub or '.'}")
    base = Path(root).resolve()
    rel = target.relative_to(base)
    head = f"🌳 {rel if str(rel) != '.' else base.name}"
    out: list[str] = []

    def walk(d: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            kids = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            return
        for p in kids:
            if p.is_dir() and p.name in _SKIP_DIRS:
                out.append(f"{prefix}{p.name}/ …")
                continue
            out.append(f"{prefix}{p.name}{'/' if p.is_dir() else ''}")
            if p.is_dir():
                walk(p, prefix + "  ", depth + 1)

    walk(target, "  ", 1)
    return head, out


def _run_source(root, cmd: str, arg: str) -> tuple[str, list[str]]:
    if cmd == "ls":
        return _ls_lines(root, arg)
    if cmd == "tree":
        return _tree_lines(root, arg)
    if cmd == "cat":
        path, _, rng = arg.partition(" ")
        return _cat_lines(root, _unquote(path), rng.strip())
    if cmd == "grep":
        return _grep_lines(root, arg)
    raise ViewError(f"Pipeline must start with {'/'.join(_SOURCES)} (got /{cmd}).")


# --------------------------------------------------------------------------- #
# public single-command wrappers (header + body)
# --------------------------------------------------------------------------- #
def _render(head: str, lines: list[str], empty: str = "(empty)") -> str:
    return _cap(head + "\n" + ("\n".join(lines) or empty))


def ls(root, sub: str = "") -> str:
    try:
        return _render(*_ls_lines(root, sub))
    except ViewError as exc:
        return str(exc)


def cat(root, sub: str, rng: str = "") -> str:
    try:
        return _render(*_cat_lines(root, sub, rng))
    except ViewError as exc:
        return str(exc)


def grep(root, pattern: str, max_hits: int = _MAX_GREP_HITS) -> str:
    try:
        return _render(*_grep_lines(root, pattern, max_hits))
    except ViewError as exc:
        return str(exc)


def tree(root, sub: str = "", max_depth: int = 2) -> str:
    try:
        return _render(*_tree_lines(root, sub, max_depth))
    except ViewError as exc:
        return str(exc)


# --------------------------------------------------------------------------- #
# `|` pipelines: <source> [args] | grep <re> | head [n] | tail [n] | nl | wc
# --------------------------------------------------------------------------- #
def _apply_filter(lines: list[str], name: str, arg: str) -> list[str]:
    if name == "grep":
        arg = _unquote(arg)
        if not arg:
            raise ViewError("grep in a pipe needs a pattern: … | grep <regex>")
        try:
            rx = re.compile(arg, re.IGNORECASE)
        except re.error as exc:
            raise ViewError(f"Bad regex: {exc}")
        return [ln for ln in lines if rx.search(ln)]
    if name == "head":
        n = int(arg) if arg.strip().isdigit() else 10
        return lines[:n]
    if name == "tail":
        n = int(arg) if arg.strip().isdigit() else 10
        return lines[-n:] if n else []
    if name == "nl":
        return [f"{i}\t{ln}" for i, ln in enumerate(lines, 1)]
    if name == "wc":
        return [f"{len(lines)} lines"]
    raise ViewError(f"Unknown filter '{name}'. Use: {', '.join(_FILTERS)}.")


def pipeline(root, text: str) -> str:
    """Run `<source> | filter | filter …`. Returns final text (caller redacts)."""
    stages = [s.strip() for s in text.split("|")]
    src = stages[0].split(maxsplit=1)
    scmd = src[0].lower() if src else ""
    sarg = src[1] if len(src) > 1 else ""
    try:
        header, lines = _run_source(root, scmd, sarg)
        if not lines and scmd == "ls":
            lines = ["(empty)"]
        for stage in stages[1:]:
            if not stage:
                continue
            fp = stage.split(maxsplit=1)
            lines = _apply_filter(lines, fp[0].lower(), fp[1] if len(fp) > 1 else "")
    except ViewError as exc:
        return str(exc)
    tail_note = f"  ({len(lines)} line(s))" if len(stages) > 1 else ""
    return _cap(header + tail_note + "\n" + ("\n".join(lines) or "(no lines)"))
