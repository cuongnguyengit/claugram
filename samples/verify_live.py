"""End-to-end verification with REAL Claude sessions and a fake Telegram.

Copies samples/hello-project to a temp dir, configures claugram with the fake
transport + short timeouts, then drives real `claude -p` runs through the
controller. Hooks fire in the spawned claude process and write to the shared
fake channel. Finally it drives the bot (fake inbound) for /sessions and
/status. Prints a PASS/FAIL report. No network beyond the claude CLI.

Run:  python samples/verify_live.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "samples" / "hello-project"

checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, bool(ok), detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" — {detail}" if detail else ""))


def setup_env() -> tuple[Path, Path]:
    workroot = Path(tempfile.mkdtemp(prefix="claugram_live_"))
    home = workroot / "home"
    fake_dir = home / "fake"
    proj = workroot / "hello-project"
    shutil.copytree(SAMPLE, proj)

    os.environ["CLAUGRAM_HOME"] = str(home)
    os.environ["CLAUGRAM_TRANSPORT"] = "fake"
    os.environ["CLAUGRAM_FAKE_DIR"] = str(fake_dir)
    os.environ["CLAUGRAM_PROJECT"] = str(proj)
    return proj, fake_dir


def configure(proj: Path) -> None:
    from claugram.config import Config, write_config
    from claugram.config.models import (
        TelegramConfig, ApprovalConfig, ControllerConfig, ClaudeConfig)
    from claugram.claude.settings_patch import patch_settings
    from claugram.claude.claude_md_patch import patch_claude_md

    cfg = Config()
    cfg.project_name = "hello-project"
    cfg.project_root = str(proj)
    cfg.telegram = TelegramConfig(transport="fake", allowed_chat_ids=[999])
    cfg.approval = ApprovalConfig(stop_reply_timeout_sec=3, permission_timeout_sec=10,
                                  max_continue_rounds=1)
    # acceptEdits so headless claude can write; attach_mcp off so it never
    # blocks on ask_user_question with no terminal.
    cfg.claude = ClaudeConfig(default_permission_mode="acceptEdits")
    cfg.controller = ControllerConfig(attach_mcp=False, max_turns=8)
    write_config(proj, cfg)

    patch_settings(proj)          # installs hooks + injects env into settings
    patch_claude_md(proj)
    return cfg


def run_task(proj, cfg, command: str, prompt: str, timeout: float = 240.0) -> str:
    from claugram.runtime import Runtime
    from claugram.controller import runner

    rt = Runtime(proj, cfg)
    jid = rt.store.enqueue_job(rt.project_id, 999, command, prompt)
    job = rt.store.claim_next_job()
    box: dict = {}

    def work():
        box["result"] = runner.run_job(rt, job)

    t = threading.Thread(target=work)
    t.start()
    t.join(timeout=timeout)
    timed_out = t.is_alive()
    rt.close()
    return "" if timed_out else box.get("result", "")


def main() -> int:
    proj, fake_dir = setup_env()
    print(f"workdir: {proj}\nhome:    {os.environ['CLAUGRAM_HOME']}\n")

    from claugram.claude.cli import find_claude
    if not find_claude():
        check("claude CLI available", False, "not on PATH — cannot run live test")
        return 1
    check("claude CLI available", True, find_claude())

    cfg = configure(proj)

    # settings.local.json got the injected env (requirement #1)
    import json
    settings = json.loads((proj / ".claude" / "settings.local.json").read_text())
    env_block = settings.get("env", {})
    check("settings.local.json injects CLAUGRAM_PROJECT",
          env_block.get("CLAUGRAM_PROJECT") == str(proj.resolve()),
          str(env_block))

    from claugram.telegram.fake import FakeControl
    ctrl = FakeControl(fake_dir)

    # ---- Task 1: create a file (exercises Write -> PostToolUse notify, Stop) ----
    print("\n>>> Task 1: create hello.txt")
    run_task(proj, cfg, "code",
             "Create a file named hello.txt in the current directory containing "
             "exactly the text: Hi from Claude. Do not create other files.")
    hello = proj / "hello.txt"
    check("Task 1 created hello.txt", hello.exists(),
          hello.read_text(encoding="utf-8").strip() if hello.exists() else "missing")

    texts = ctrl.sent_texts()
    check("PostToolUse notified an edit to Telegram",
          any("Edited file" in t for t in texts),
          f"{len(texts)} messages sent")
    check("Controller sent a final summary",
          any("Done" in t or "Claude error" in t for t in texts))
    check("Messages carry a project · session tag",
          any("hello-project · " in t for t in texts),
          "tag <project> · <sess8> present")

    print("\n--- sample Telegram messages (first line each) ---")
    for t in texts:
        print("  " + t.splitlines()[0])

    # ---- Task 2: second session ----
    print("\n>>> Task 2: create notes.md")
    run_task(proj, cfg, "code",
             "Create a file named notes.md containing a single line: sample notes.")
    check("Task 2 created notes.md", (proj / "notes.md").exists())

    # ---- Session discovery ----
    from claugram.claude import sessions_disk
    sessions = sessions_disk.list_sessions(proj, limit=10)
    check("Claude sessions discoverable on disk", len(sessions) >= 2,
          f"{len(sessions)} session(s): {[s.short for s in sessions]}")

    from claugram.runtime import Runtime
    rt = Runtime(proj, cfg)
    db_sessions = rt.store.conn.execute(
        "SELECT COUNT(*) c FROM sessions WHERE project_id=?", (rt.project_id,)
    ).fetchone()["c"]
    check("Sessions recorded in claugram store", db_sessions >= 2, f"{db_sessions} rows")

    # ---- Drive the bot (fake inbound) for /sessions and /session/select ----
    from claugram.telegram.polling import BotPoller, BotContext
    from claugram.controller import registry
    from claugram.cli_helpers import status_lines
    ref = registry.by_id(rt.store, rt.project_id)
    ctx = BotContext(
        store=rt.store, client=rt.client, allowed_chat_ids={999},
        resolve_project=lambda cid: ref,
        select_project=lambda cid, arg: ref,
        list_projects=lambda: [ref],
        enqueue=lambda c, p, ch: rt.store.enqueue_job(rt.project_id, ch, c, p),
        status_provider=lambda cid: "\n".join(status_lines(rt)))
    poller = BotPoller(ctx)

    before = len(ctrl.sent_texts())
    poller._dispatch({"update_id": 1, "message": {"chat": {"id": 999}, "text": "/sessions"}})
    sessions_msg = ctrl.sent_texts()[-1]
    check("/sessions lists the sessions over Telegram",
          "Sessions in" in sessions_msg and len(sessions) >= 2)

    if sessions:
        poller._dispatch({"update_id": 2,
                          "message": {"chat": {"id": 999}, "text": "/session 1"}})
        active = rt.store.get_active_session(rt.project_id)
        check("/session 1 selects a session", active == sessions[0].session_id,
              (active or "")[:8])

    poller._dispatch({"update_id": 3, "message": {"chat": {"id": 999}, "text": "/status"}})
    check("/status responds", "Project:" in ctrl.sent_texts()[-1])

    rt.close()

    print("\n=== SUMMARY ===")
    passed = sum(1 for _, ok, _ in checks if ok)
    print(f"{passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
