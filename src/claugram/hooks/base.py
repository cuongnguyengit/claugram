"""Shared helpers for hook handlers.

Hooks read a JSON event on stdin and may print a JSON decision on stdout.
Golden rule: a hook must never crash Claude Code. On any failure we log and
exit 0 with no decision (which Claude treats as "no opinion").
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from ..runtime import Runtime, setup_logging
from ..config import try_load_config

log = logging.getLogger("claugram.hook")


def read_event() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def emit(decision: Optional[dict] = None) -> None:
    """Print a JSON decision (or nothing) and exit 0."""
    if decision:
        sys.stdout.write(json.dumps(decision))
        sys.stdout.flush()
    raise SystemExit(0)


def project_root_from_event(event: dict) -> Path:
    cwd = event.get("cwd") or event.get("project_dir")
    if cwd:
        return Path(cwd)
    import os
    return Path(os.environ.get("CLAUGRAM_PROJECT", Path.cwd()))


def build_runtime(event: dict) -> Optional[Runtime]:
    """Build a Runtime, or None if claugram is not configured here."""
    root = project_root_from_event(event)
    config = try_load_config(root)
    if config is None or not config.telegram.allowed_chat_ids:
        return None
    try:
        return Runtime(root, config)
    except Exception:
        log.exception("failed to build runtime")
        return None


def run_hook(handler) -> None:
    """Wrap a handler(event, runtime|None) so it can never break Claude."""
    setup_logging("hook")
    try:
        event = read_event()
    except Exception:
        log.exception("failed to read hook event")
        emit(None)
        return
    try:
        rt = build_runtime(event)
        decision = handler(event, rt)
    except SystemExit:
        raise
    except Exception:
        log.exception("hook handler error")
        decision = None
    emit(decision)
