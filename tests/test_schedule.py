from datetime import datetime

from claugram.config.models import Config, ScheduleConfig
from claugram.schedule import should_forward


def _cfg(**kw) -> Config:
    c = Config()
    c.schedule = ScheduleConfig(**kw)
    return c


def test_default_always_on():
    assert should_forward(_cfg()) is True


def test_env_mute_wins(monkeypatch):
    monkeypatch.setenv("CLAUGRAM_MUTE", "1")
    assert should_forward(_cfg()) is False  # even without schedule


def test_env_always_wins(monkeypatch):
    monkeypatch.setenv("CLAUGRAM_ALWAYS", "yes")
    cfg = _cfg(respect_schedule=True, active_days=["mon"], active_window="09:00-10:00")
    # a Saturday, outside window, but ALWAYS overrides
    assert should_forward(cfg, datetime(2026, 7, 11, 3, 0)) is True


def test_schedule_window(monkeypatch):
    monkeypatch.delenv("CLAUGRAM_MUTE", raising=False)
    monkeypatch.delenv("CLAUGRAM_ALWAYS", raising=False)
    cfg = _cfg(respect_schedule=True,
               active_days=["mon", "tue", "wed", "thu", "fri"],
               active_window="09:00-18:00")
    # 2026-07-13 is a Monday
    assert should_forward(cfg, datetime(2026, 7, 13, 10, 0)) is True   # Mon 10:00
    assert should_forward(cfg, datetime(2026, 7, 13, 20, 0)) is False  # Mon 20:00
    assert should_forward(cfg, datetime(2026, 7, 11, 10, 0)) is False  # Sat 10:00


def test_overnight_window():
    cfg = _cfg(respect_schedule=True, active_days=["mon"], active_window="22:00-06:00")
    assert should_forward(cfg, datetime(2026, 7, 13, 23, 0)) is True   # Mon 23:00
    assert should_forward(cfg, datetime(2026, 7, 13, 5, 0)) is True    # Mon 05:00
    assert should_forward(cfg, datetime(2026, 7, 13, 12, 0)) is False  # Mon noon
