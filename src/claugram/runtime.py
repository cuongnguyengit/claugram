"""Shared runtime wiring used by the bot, MCP server, hooks and controller."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from .config import Config, load_config, resolve_bot_token, paths
from .storage import Store
from .telegram import TelegramClient
from .security import redact


def setup_logging(name: str = "claugram") -> None:
    paths.ensure_user_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(paths.logs_dir() / f"{name}.log", encoding="utf-8"),
        ],
    )


class Runtime:
    """Bundles the resolved config, store and Telegram client for one project."""

    def __init__(self, project_root: Path, config: Optional[Config] = None):
        self.project_root = Path(project_root).resolve()
        self.config = config or load_config(self.project_root)
        self.store = Store()
        self.project_id = self.store.upsert_project(
            self.config.project_name or self.project_root.name,
            str(self.project_root),
        )
        self._client: Optional[TelegramClient] = None

    @property
    def client(self):
        """The message transport (real Telegram or the fake test channel)."""
        if self._client is None:
            self._client = self._build_transport()
        return self._client

    def _build_transport(self):
        mode = os.environ.get("CLAUGRAM_TRANSPORT") or self.config.telegram.transport
        if mode == "fake":
            from .telegram.fake import FakeTransport
            base = os.environ.get("CLAUGRAM_FAKE_DIR") or str(paths.user_config_dir() / "fake")
            return FakeTransport(Path(base))
        token = resolve_bot_token(self.config.telegram.bot_token_ref)
        if not token:
            raise RuntimeError(
                "No Telegram bot token resolved from "
                f"{self.config.telegram.bot_token_ref!r}. Run `claugram init`."
            )
        return TelegramClient(token)

    @property
    def primary_chat_id(self) -> int:
        ids = self.config.telegram.allowed_chat_ids
        if not ids:
            raise RuntimeError("No allowed_chat_ids configured.")
        return int(ids[0])

    @property
    def allowed_chat_ids(self) -> set[int]:
        return {int(c) for c in self.config.telegram.allowed_chat_ids}

    def send(self, chat_id: int, text: str, **kwargs) -> dict:
        """Send a message, always redacting secrets first."""
        return self.client.send_message(chat_id, redact(text), **kwargs)

    def session_label(self, session_id: Optional[str]) -> str:
        """Human display token for a session: its name if set, else short id."""
        if not session_id:
            return ""
        name = self.store.get_session_name(session_id)
        return name or str(session_id)[:8]

    def forwarding_enabled(self) -> bool:
        """Whether hooks/tools may reach Telegram right now (schedule + env)."""
        from .schedule import should_forward
        return should_forward(self.config)

    def close(self) -> None:
        self.store.close()
