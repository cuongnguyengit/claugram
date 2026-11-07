"""Resolve a chat_id during onboarding by reading recent bot updates."""

from __future__ import annotations

import time
from typing import Optional

from .client import TelegramClient, TelegramError


def token_has_active_poller(client: TelegramClient) -> Optional[bool]:
    """Best-effort check: is another process already long-polling this token?

    Telegram allows only one getUpdates consumer per token, so a running
    `claugram bot`/`hub` makes a probe call fail with 409 Conflict. Returns
    True if a poller is active, False if the probe succeeds (none running),
    or None if it couldn't be determined (network/other error). The probe uses
    timeout=0 and does not confirm the offset, so it doesn't consume updates.
    """
    try:
        client.get_updates(offset=None, timeout=0)
        return False
    except TelegramError as exc:
        if "Conflict" in str(exc):
            return True
        return None


def resolve_chat_id(client: TelegramClient, wait_sec: int = 60) -> int | None:
    """Poll getUpdates until a human sends a message; return their chat_id.

    Intended for interactive `claugram init`. The user is told to send /start.
    """
    deadline = time.monotonic() + wait_sec
    offset = None
    while time.monotonic() < deadline:
        updates = client.get_updates(offset=offset, timeout=10)
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message")
            if msg and msg.get("chat", {}).get("id") is not None:
                return int(msg["chat"]["id"])
    return None
