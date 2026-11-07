"""Session/project tags in messages + ambiguous-reply disambiguation."""

import pytest

from claugram.telegram import formatting
from claugram.storage import Store


def test_tag_and_headers():
    # tag takes an already-resolved display token (name or short id)
    assert formatting.tag("proj", "3427ce1b") == "proj · 3427ce1b"
    assert formatting.tag("proj", "risk-refactor") == "proj · risk-refactor"
    assert formatting.tag("proj") == "proj"
    assert "proj · 3427ce1b" in formatting.notification(
        "Edited", "x", project="proj", session="3427ce1b")
    assert "proj · 3427ce1b" in formatting.question(
        "A or B?", project="proj", session="3427ce1b")
    assert "proj · 3427ce1b" in formatting.permission(
        "Bash", {"command": "git push"}, "high", "why", project="proj",
        session="3427ce1b")


def test_session_label_uses_name(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUGRAM_HOME", str(tmp_path / "home"))
    from claugram.config import Config, write_config
    from claugram.config.models import TelegramConfig
    cfg = Config()
    cfg.project_name = "demo"
    cfg.project_root = str(tmp_path)
    cfg.telegram = TelegramConfig(transport="fake", allowed_chat_ids=[1])
    write_config(tmp_path, cfg)
    monkeypatch.setenv("CLAUGRAM_TRANSPORT", "fake")
    monkeypatch.setenv("CLAUGRAM_FAKE_DIR", str(tmp_path / "fake"))
    from claugram.runtime import Runtime
    rt = Runtime(tmp_path, cfg)
    sid = "abcd1234-0000-0000-0000-000000000000"
    assert rt.session_label(sid) == "abcd1234"          # falls back to short id
    rt.store.set_session_name(sid, "risk-refactor")
    assert rt.session_label(sid) == "risk-refactor"     # uses the name
    assert rt.session_label(None) == ""
    rt.close()


def _poller(store, client):
    from claugram.telegram.polling import BotPoller, BotContext
    ctx = BotContext(
        store=store, client=client, allowed_chat_ids={999},
        resolve_project=lambda cid: None,
        select_project=lambda cid, arg: None,
        list_projects=lambda: [],
        enqueue=lambda c, p, ch: None,
        status_provider=lambda cid: "ok")
    return BotPoller(ctx)


def test_ambiguous_reply_requires_direct_reply(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUGRAM_TRANSPORT", "fake")
    monkeypatch.setenv("CLAUGRAM_FAKE_DIR", str(tmp_path / "fake"))
    from claugram.telegram.fake import FakeTransport, FakeControl

    store = Store(tmp_path / "state.sqlite3")
    pa = store.upsert_project("alpha", str(tmp_path / "alpha"))
    pb = store.upsert_project("beta", str(tmp_path / "beta"))
    q1 = store.create_question(pa, "sessaaaa1111", 999, "Do A?", None, 60)
    store.attach_question_message(q1, 501)
    q2 = store.create_question(pb, "sessbbbb2222", 999, "Do B?", None, 60)
    store.attach_question_message(q2, 502)

    ctrl = FakeControl(tmp_path / "fake")
    poller = _poller(store, FakeTransport(tmp_path / "fake"))
    poller._dispatch({"update_id": 1,
                      "message": {"chat": {"id": 999}, "text": "ok go"}})

    last = ctrl.sent_texts()[-1]
    assert "Multiple things are waiting" in last
    assert "alpha · sessaaaa" in last and "beta · sessbbbb" in last
    # neither question was answered
    assert store.get_question(q1)["status"] == "pending"
    assert store.get_question(q2)["status"] == "pending"

    # a DIRECT reply to message 502 answers exactly that one
    poller._dispatch({"update_id": 2, "message": {
        "chat": {"id": 999}, "text": "yes B",
        "reply_to_message": {"message_id": 502}}})
    assert store.get_question(q2)["status"] == "answered"
    assert store.get_question(q1)["status"] == "pending"
    store.close()
