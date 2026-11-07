"""Integration: MCP tool blocks, the 'bot' answers via the shared store."""

import os
import threading
import time

import pytest

from claugram.config import Config, write_config
from claugram.config.models import TelegramConfig


class FakeClient:
    def __init__(self):
        self.sent = []
        self._mid = 1000

    def send_message(self, chat_id, text, **kwargs):
        self._mid += 1
        self.sent.append((chat_id, text))
        return {"message_id": self._mid}


@pytest.fixture()
def rt(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUGRAM_HOME", str(tmp_path / "home"))
    cfg = Config()
    cfg.project_name = "demo"
    cfg.project_root = str(tmp_path)
    cfg.telegram = TelegramConfig(bot_token_ref="raw:x", allowed_chat_ids=[999])
    write_config(tmp_path, cfg)

    from claugram.runtime import Runtime
    runtime = Runtime(tmp_path, cfg)
    runtime._client = FakeClient()
    yield runtime
    runtime.close()


def test_ask_answer_flow(rt):
    from claugram.mcp import tools

    result = {}

    def ask():
        result["value"] = tools.do_ask(rt, "A or B?", options=["A", "B"], timeout_sec=10)

    t = threading.Thread(target=ask)
    t.start()

    # simulate the bot: find the pending question and answer it
    deadline = time.monotonic() + 5
    q = None
    while time.monotonic() < deadline:
        q = rt.store.latest_open_question(999)
        if q:
            break
        time.sleep(0.1)
    assert q is not None, "question was never created"
    rt.store.answer_question(q["id"], "B", 999)

    t.join(timeout=5)
    assert result["value"]["answer"] == "B"
    assert result["value"]["timed_out"] is False


def test_permission_deny_flow(rt):
    from claugram.mcp import tools

    result = {}

    def ask():
        result["value"] = tools.do_request_permission(
            rt, "Bash", {"command": "git push"}, risk_level="high",
            reason="publishes code", timeout_sec=10)

    t = threading.Thread(target=ask)
    t.start()

    deadline = time.monotonic() + 5
    p = None
    while time.monotonic() < deadline:
        p = rt.store.latest_open_permission(999)
        if p:
            break
        time.sleep(0.1)
    assert p is not None
    rt.store.decide_permission(p["id"], "deny", 999, "no push")

    t.join(timeout=5)
    assert result["value"]["decision"] == "deny"
