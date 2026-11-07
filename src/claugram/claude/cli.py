"""Locate and drive the `claude` CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterator, Optional


def find_claude() -> Optional[str]:
    found = shutil.which("claude")
    if found:
        return found
    # common Windows install locations
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "claude" / "claude.exe",
        Path.home() / ".local" / "bin" / "claude",
    ]
    for c in candidates:
        if c and c.exists():
            return str(c)
    return None


def claude_version() -> Optional[str]:
    exe = find_claude()
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                             timeout=20)
        return out.stdout.strip() or out.stderr.strip() or None
    except (subprocess.SubprocessError, OSError):
        return None


def build_headless_args(
    prompt: str,
    session_id: Optional[str] = None,
    continue_last: bool = False,
    output_format: str = "stream-json",
    mcp_config: Optional[str] = None,
    permission_mode: Optional[str] = None,
    max_turns: Optional[int] = None,
) -> list[str]:
    exe = find_claude() or "claude"
    args = [exe, "-p", prompt, "--output-format", output_format]
    if output_format == "stream-json":
        args.append("--verbose")
    # The built-in AskUserQuestion tool renders only in an interactive terminal;
    # in headless (-p) it cannot reach the remote user and would stall the run.
    # Disallow it so Claude is forced onto mcp__claugram__ask_user_question,
    # which routes to Telegram and returns the chosen answer.
    args += ["--disallowedTools", "AskUserQuestion"]
    if session_id:
        args += ["--resume", session_id]
    elif continue_last:
        args.append("--continue")
    if mcp_config:
        # use ONLY our server; don't inherit the user's other (heavy) MCP servers
        args += ["--mcp-config", mcp_config, "--strict-mcp-config"]
    if permission_mode:
        args += ["--permission-mode", permission_mode]
    if max_turns:
        args += ["--max-turns", str(max_turns)]
    return args


def stream_headless(
    project_root: Path,
    prompt: str,
    session_id: Optional[str] = None,
    continue_last: bool = False,
    mcp_config: Optional[str] = None,
    permission_mode: Optional[str] = None,
    max_turns: Optional[int] = None,
    idle_timeout_sec: Optional[int] = None,
) -> Iterator[dict]:
    """Run `claude -p ... --output-format stream-json` and yield parsed events.

    stdout/stderr are decoded as UTF-8 (claude emits UTF-8 regardless of the
    Windows console codepage). An *idle* watchdog kills the process only if it
    produces NO output for ``idle_timeout_sec`` seconds — a long but productive
    run (e.g. resuming a huge session) keeps streaming and is never killed.
    """
    import threading

    args = build_headless_args(
        prompt, session_id=session_id, continue_last=continue_last,
        output_format="stream-json", mcp_config=mcp_config,
        permission_mode=permission_mode, max_turns=max_turns)
    # Signal our hooks that they run *inside* a controller headless run, so the
    # Stop hook doesn't block waiting for a Telegram reply (which would hang
    # `claude -p` forever — the controller manages continuation via /continue).
    child_env = {**os.environ, "CLAUGRAM_IN_CONTROLLER": "1"}
    proc = subprocess.Popen(
        args, cwd=str(project_root), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
        bufsize=1, env=child_env,
    )
    assert proc.stdout is not None

    # idle watchdog: kill only after idle_timeout_sec with no output at all.
    state = {"stuck": False, "timer": None}

    def _kill():
        state["stuck"] = True
        try:
            proc.kill()
        except OSError:
            pass

    def _arm():
        if not idle_timeout_sec:
            return
        t = threading.Timer(idle_timeout_sec, _kill)
        t.daemon = True
        t.start()
        state["timer"] = t

    def _reset():
        if state["timer"]:
            state["timer"].cancel()
        _arm()

    _arm()
    try:
        for line in proc.stdout:
            _reset()  # any output means it's alive, not stuck
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                yield {"type": "raw", "text": line}
    finally:
        if state["timer"]:
            state["timer"].cancel()
        proc.wait()
        if state["stuck"]:
            yield {"type": "error",
                   "text": f"claude produced no output for {idle_timeout_sec}s "
                           "(appears stuck) and was stopped"}
        elif proc.returncode not in (0, None):
            err = proc.stderr.read() if proc.stderr else ""
            yield {"type": "error", "text": err.strip() or
                   f"claude exited with code {proc.returncode}"}
