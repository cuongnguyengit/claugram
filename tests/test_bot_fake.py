"""Bot/hook behavior driven through the FakeTransport (no network)."""

import threading
import time

import pytest

from claugram.config import Config, write_config
from claugram.config.models import TelegramConfig, ApprovalConfig
from claugram.telegram.fake import FakeControl


@pytest.fixture()
def fake_rt(tmp_path, monkeypatch):
    home = tmp_path / "home"
    fake_dir = home / "fake"
    monkeypatch.setenv("CLAUGRAM_HOME", str(home))
    monkeypatch.setenv("CLAUGRAM_TRANSPORT", "fake")
    monkeypatch.setenv("CLAUGRAM_FAKE_DIR", str(fake_dir))

    proj = tmp_path / "proj"
    proj.mkdir()
    cfg = Config()
    cfg.project_name = "demo"
    cfg.project_root = str(proj)
    cfg.telegram = TelegramConfig(transport="fake", allowed_chat_ids=[999])
    cfg.approval = ApprovalConfig(stop_reply_timeout_sec=10, permission_timeout_sec=10)
    write_config(proj, cfg)

    from claugram.runtime import Runtime
    rt = Runtime(proj, cfg)
    ctrl = FakeControl(fake_dir)
    yield rt, ctrl, proj
    rt.close()


def _poller(rt, proj):
    from claugram.telegram.polling import BotPoller, BotContext
    from claugram.controller.registry import ProjectRef
    enqueued = []
    ref = ProjectRef(rt.project_id, "demo", proj)

    def enqueue(cmd, prompt, chat_id):
        enqueued.append((cmd, prompt, chat_id))
        return rt.store.enqueue_job(rt.project_id, chat_id, cmd, prompt)

    ctx = BotContext(store=rt.store, client=rt.client, allowed_chat_ids={999},
                     resolve_project=lambda cid: ref,
                     select_project=lambda cid, arg: ref,
                     list_projects=lambda: [ref],
                     enqueue=enqueue,
                     status_provider=lambda cid: "STATUS-OK")
    return BotPoller(ctx), enqueued


def test_poller_run_loop_smoke(fake_rt):
    # exercises BotPoller.run() startup (tests otherwise only call _dispatch)
    rt, ctrl, proj = fake_rt
    poller, _ = _poller(rt, proj)
    calls = {"n": 0}

    def fake_get_updates(offset=None, timeout=30, allowed_updates=None):
        calls["n"] += 1
        poller.stop()
        return []

    poller.ctx.client.get_updates = fake_get_updates
    poller.run()  # must not raise (regression: ctx.project_name removed)
    assert calls["n"] == 1
    # startup registers the "/" autocomplete menu with Telegram
    cmds = [o for o in ctrl._outbox() if o.get("kind") == "set_commands"]
    assert cmds and cmds[0]["count"] >= 10


def test_status_command(fake_rt):
    rt, ctrl, proj = fake_rt
    poller, _ = _poller(rt, proj)
    poller._dispatch({"update_id": 1, "message": {"chat": {"id": 999}, "text": "/status"}})
    assert "STATUS-OK" in ctrl.sent_texts()[-1]


def test_unauthorized_chat_ignored(fake_rt):
    rt, ctrl, proj = fake_rt
    poller, enqueued = _poller(rt, proj)
    poller._dispatch({"update_id": 1, "message": {"chat": {"id": 555}, "text": "/status"}})
    assert ctrl.sent_texts() == []  # nothing sent to a non-whitelisted chat


def test_code_command_enqueues(fake_rt):
    rt, ctrl, proj = fake_rt
    poller, enqueued = _poller(rt, proj)
    poller._dispatch({"update_id": 1,
                      "message": {"chat": {"id": 999}, "text": "/code fix bug"}})
    assert enqueued == [("code", "fix bug", 999)]
    assert "Queued" in ctrl.sent_texts()[-1]


def test_button_answers_question(fake_rt):
    rt, ctrl, proj = fake_rt
    poller, _ = _poller(rt, proj)
    qid = rt.store.create_question(rt.project_id, None, 999, "A or B?", ["A", "B"], 60)
    rt.store.attach_question_message(qid, 500)
    poller._dispatch({"update_id": 1, "callback_query": {
        "id": "cb1", "data": f"q|{qid[:16]}|1", "from": {"id": 999},
        "message": {"chat": {"id": 999}, "message_id": 500}}})
    row = rt.store.get_question(qid)
    assert row["status"] == "answered" and row["answer_text"] == "B"


def test_reply_answers_latest_question(fake_rt):
    rt, ctrl, proj = fake_rt
    poller, _ = _poller(rt, proj)
    qid = rt.store.create_question(rt.project_id, None, 999, "why?", None, 60)
    rt.store.attach_question_message(qid, 501)
    poller._dispatch({"update_id": 1,
                      "message": {"chat": {"id": 999}, "text": "because reasons"}})
    row = rt.store.get_question(qid)
    assert row["status"] == "answered" and row["answer_text"] == "because reasons"


def test_stop_hook_continues_on_reply(fake_rt):
    rt, ctrl, proj = fake_rt
    from claugram.hooks import stop as stop_hook

    result = {}
    event = {"session_id": "s1", "stop_hook_active": False,
             "transcript_path": "", "cwd": str(proj)}

    def run():
        result["decision"] = stop_hook.handle(event, rt)

    t = threading.Thread(target=run)
    t.start()
    # act as the human: find the stop question and reply "run more tests"
    deadline = time.monotonic() + 5
    q = None
    while time.monotonic() < deadline:
        q = rt.store.latest_open_question(999)
        if q:
            break
        time.sleep(0.1)
    assert q is not None
    rt.store.answer_question(q["id"], "run more tests", 999)
    t.join(timeout=5)
    assert result["decision"] == {"decision": "block", "reason": "run more tests"}


def test_stop_hook_muted_lets_stop(fake_rt, monkeypatch):
    rt, ctrl, proj = fake_rt
    monkeypatch.setenv("CLAUGRAM_MUTE", "1")
    from claugram.hooks import stop as stop_hook
    decision = stop_hook.handle({"session_id": "s1", "stop_hook_active": False,
                                 "cwd": str(proj)}, rt)
    assert decision is None
    assert ctrl.sent_texts() == []  # nothing forwarded while muted
