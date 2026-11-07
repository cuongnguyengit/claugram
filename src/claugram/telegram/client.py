"""Thin Telegram Bot API client over stdlib urllib (no extra dependency)."""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from typing import Any, Optional


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, bot_token: str, base_url: str = "https://api.telegram.org"):
        if not bot_token:
            raise TelegramError("Empty bot token")
        self.bot_token = bot_token
        self.base_url = base_url.rstrip("/")

    def _call(self, method: str, payload: dict[str, Any], timeout: float = 40.0) -> dict:
        url = f"{self.base_url}/bot{self.bot_token}/{method}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except Exception:
                raise TelegramError(f"{method} failed: HTTP {exc.code}") from exc
            desc = body.get("description", f"HTTP {exc.code}")
            raise TelegramError(f"{method} failed: {desc}") from exc
        except urllib.error.URLError as exc:
            raise TelegramError(f"{method} network error: {exc.reason}") from exc
        except (TimeoutError, ConnectionError, http.client.HTTPException,
                OSError) as exc:
            # read timeouts, resets, RemoteDisconnected, SSL errors, etc. arrive
            # here (NOT as URLError). Wrap them so the poller retries instead of
            # crashing — corporate networks/proxies drop long-poll reads often.
            raise TelegramError(f"{method} network error: {exc!r}") from exc

        if not body.get("ok"):
            raise TelegramError(f"{method} error: {body.get('description')}")
        return body.get("result", {})

    # ----- api methods -----
    def get_me(self) -> dict:
        return self._call("getMe", {}, timeout=15.0)

    def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: Optional[str] = None,
        reply_markup: Optional[dict] = None,
        disable_notification: bool = False,
    ) -> dict:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text[:4096],
            "disable_notification": disable_notification,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            return self._call("sendMessage", payload)
        except TelegramError:
            # Retry once without parse_mode in case of markdown entity errors.
            if parse_mode:
                payload.pop("parse_mode", None)
                return self._call("sendMessage", payload)
            raise

    def edit_message_reply_markup(self, chat_id: int, message_id: int,
                                  reply_markup: Optional[dict] = None) -> dict:
        payload = {"chat_id": chat_id, "message_id": message_id}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        else:
            payload["reply_markup"] = {"inline_keyboard": []}
        return self._call("editMessageReplyMarkup", payload)

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> dict:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return self._call("answerCallbackQuery", payload)

    def set_my_commands(self, commands: list[tuple[str, str]]) -> dict:
        """Register the slash-command autocomplete menu shown in Telegram.

        `commands` is a list of (command, description); the leading '/' is
        stripped and names are lowercased to satisfy the Bot API.
        """
        payload = {"commands": [
            {"command": c.lstrip("/").lower()[:32], "description": d[:256]}
            for c, d in commands
        ]}
        return self._call("setMyCommands", payload, timeout=15.0)

    def get_updates(self, offset: Optional[int] = None, timeout: int = 30,
                    allowed_updates: Optional[list[str]] = None) -> list[dict]:
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates
        # network timeout must exceed long-poll timeout
        return self._call("getUpdates", payload, timeout=timeout + 15.0)
