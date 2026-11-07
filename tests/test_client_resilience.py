"""Network hiccups must not crash the bot: _call wraps them, poller retries."""

import pytest

from claugram.telegram.client import TelegramClient, TelegramError


def test_call_wraps_read_timeout(monkeypatch):
    # a read timeout surfaces as a bare TimeoutError (not URLError) -> must be
    # wrapped into TelegramError so the poller can treat it as retryable.
    def boom(*a, **k):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    c = TelegramClient("123:abc")
    with pytest.raises(TelegramError):
        c.get_updates(timeout=0)


def test_call_wraps_connection_reset(monkeypatch):
    def boom(*a, **k):
        raise ConnectionResetError("reset by peer")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    c = TelegramClient("123:abc")
    with pytest.raises(TelegramError):
        c._call("getMe", {})


def test_poller_survives_getupdates_exception(monkeypatch):
    from claugram.telegram.polling import BotPoller, BotContext

    class Client:
        def __init__(self):
            self.calls = 0

        def set_my_commands(self, cmds):
            return {"ok": True}

        def get_updates(self, offset=None, timeout=30, allowed_updates=None):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("boom")          # transient, non-TelegramError
            poller.stop()                            # stop after recovering
            return []

    client = Client()
    ctx = BotContext(
        store=_FakeStore(), client=client, allowed_chat_ids={1},
        resolve_project=lambda c: None, select_project=lambda c, a: None,
        list_projects=lambda: [], enqueue=lambda c, p, ch: None,
        status_provider=lambda c: "ok")
    poller = BotPoller(ctx)
    monkeypatch.setattr("time.sleep", lambda *_: None)  # no real delay
    poller.run()  # must NOT raise despite the TimeoutError
    assert client.calls == 2  # retried after the failure


class _FakeStore:
    def kv_get(self, *a, **k):
        return None

    def kv_set(self, *a, **k):
        pass
