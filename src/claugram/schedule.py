"""Decide whether Telegram forwarding is active right now.

Precedence (highest first):
  1. env CLAUGRAM_MUTE truthy   -> never forward (master off switch)
  2. env CLAUGRAM_ALWAYS truthy -> always forward
  3. config.schedule.respect_schedule == False -> always forward
  4. otherwise: active only on active_days within active_window (in timezone)
"""

from __future__ import annotations

import os
from datetime import datetime, time as dtime
from typing import Optional

from .config.models import Config

_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_TRUTHY = {"1", "true", "yes", "on", "y"}


def _env_truthy(name: str) -> bool:
    val = os.environ.get(name)
    return bool(val) and val.strip().lower() in _TRUTHY


def _parse_window(window: str) -> tuple[dtime, dtime]:
    start_s, _, end_s = window.partition("-")
    sh, sm = (int(x) for x in start_s.strip().split(":"))
    eh, em = (int(x) for x in end_s.strip().split(":"))
    return dtime(sh, sm), dtime(eh, em)


def _now_in_tz(tz_name: str) -> datetime:
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass  # missing tzdata / bad name -> fall back to local
    return datetime.now()


def should_forward(config: Config, now: Optional[datetime] = None) -> bool:
    if _env_truthy("CLAUGRAM_MUTE"):
        return False
    if _env_truthy("CLAUGRAM_ALWAYS"):
        return True

    sc = config.schedule
    if not sc.respect_schedule:
        return True

    now = now or _now_in_tz(sc.timezone)
    day = _DAYS[now.weekday()]
    if day not in [d.lower() for d in sc.active_days]:
        return False
    try:
        start, end = _parse_window(sc.active_window)
    except (ValueError, AttributeError):
        return True  # malformed window -> don't accidentally mute everything
    t = now.time()
    if start <= end:
        return start <= t <= end
    # overnight window (e.g. 22:00-06:00)
    return t >= start or t <= end


def forwarding_status(config: Config) -> str:
    if _env_truthy("CLAUGRAM_MUTE"):
        return "muted (CLAUGRAM_MUTE)"
    if _env_truthy("CLAUGRAM_ALWAYS"):
        return "always (CLAUGRAM_ALWAYS)"
    if not config.schedule.respect_schedule:
        return "always (no schedule)"
    active = should_forward(config)
    sc = config.schedule
    return (f"{'ON' if active else 'OFF'} — {','.join(sc.active_days)} "
            f"{sc.active_window} {sc.timezone or 'local'}")
