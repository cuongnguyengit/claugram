"""Multi-project registry + /use routing (no network, real store)."""

import pytest

from claugram.storage import Store
from claugram.controller import registry


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "state.sqlite3")
    yield s
    s.close()


def test_registry_find_and_active(store, tmp_path):
    a = store.upsert_project("alpha", str(tmp_path / "alpha"))
    b = store.upsert_project("beta", str(tmp_path / "beta"))

    refs = registry.list_registered(store)
    assert {r.name for r in refs} == {"alpha", "beta"}

    assert registry.find(store, "beta").project_id == b
    assert registry.find(store, "1").project_id == a           # 1-based index
    assert registry.find(store, "alp").project_id == a          # prefix
    assert registry.find(store, "nope") is None

    default = registry.by_id(store, a)
    # no selection -> default
    assert registry.active_ref(store, 999, default).project_id == a
    # select beta for this chat
    store.set_active_project(999, b)
    assert registry.active_ref(store, 999, default).project_id == b
    # a different chat still gets the default
    assert registry.active_ref(store, 111, default).project_id == a


def test_use_command_routes_jobs(store, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUGRAM_TRANSPORT", "fake")
    monkeypatch.setenv("CLAUGRAM_FAKE_DIR", str(tmp_path / "fake"))
    from claugram.telegram.polling import BotPoller, BotContext
    from claugram.telegram.fake import FakeTransport

    a = store.upsert_project("alpha", str(tmp_path / "alpha"))
    b = store.upsert_project("beta", str(tmp_path / "beta"))
    default = registry.by_id(store, a)
    client = FakeTransport(tmp_path / "fake")

    def enqueue(cmd, prompt, chat_id):
        ref = registry.active_ref(store, chat_id, default)
        return store.enqueue_job(ref.project_id, chat_id, cmd, prompt)

    ctx = BotContext(
        store=store, client=client, allowed_chat_ids={999},
        resolve_project=lambda cid: registry.active_ref(store, cid, default),
        select_project=lambda cid, arg: (
            (lambda r: (store.set_active_project(cid, r.project_id), r)[1] if r else None)
            (registry.find(store, arg))),
        list_projects=lambda: registry.list_registered(store),
        enqueue=enqueue, status_provider=lambda cid: "ok")
    poller = BotPoller(ctx)

    # default project is alpha
    poller._dispatch({"update_id": 1, "message": {"chat": {"id": 999}, "text": "/code do X"}})
    job = store.claim_next_job()
    assert job["project_id"] == a

    # switch to beta, then a job routes to beta
    poller._dispatch({"update_id": 2, "message": {"chat": {"id": 999}, "text": "/use beta"}})
    poller._dispatch({"update_id": 3, "message": {"chat": {"id": 999}, "text": "/code do Y"}})
    job2 = store.claim_next_job()
    assert job2["project_id"] == b
