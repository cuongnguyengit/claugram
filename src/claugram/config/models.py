"""Typed configuration models (stdlib dataclasses, no pydantic dependency)."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class TelegramConfig:
    bot_token_ref: str = "user:default"
    allowed_chat_ids: list[int] = field(default_factory=list)
    polling_timeout_sec: int = 30
    parse_mode: str = "Markdown"
    transport: str = "telegram"  # telegram | fake (env CLAUGRAM_TRANSPORT overrides)


@dataclass
class ScheduleConfig:
    """When Telegram forwarding is active.

    respect_schedule=False (default) means always forward. When True, hooks only
    reach Telegram on active_days within active_window (in `timezone`). The
    env vars CLAUGRAM_MUTE (force off) and CLAUGRAM_ALWAYS (force on) override.
    """
    respect_schedule: bool = False
    active_days: list[str] = field(default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"])
    active_window: str = "09:00-18:00"
    timezone: str = ""  # empty -> system local time


@dataclass
class ClaudeConfig:
    mode: str = "interactive_plus_controller"
    default_permission_mode: str = "acceptEdits"
    session_strategy: str = "remember_last"
    mcp_server_name: str = "claugram"


@dataclass
class NotificationsConfig:
    notify_post_edit: bool = True
    notify_post_bash: bool = True
    notify_read_tools: bool = False
    notify_batch_summary: bool = True
    notify_stop_summary: bool = True


@dataclass
class ApprovalConfig:
    permission_timeout_sec: int = 86400
    stop_reply_timeout_sec: int = 3600
    default_on_timeout: str = "deny"  # deny | allow
    max_continue_rounds: int = 6


@dataclass
class SecurityConfig:
    deny_shell_patterns: list[str] = field(default_factory=lambda: [
        "rm -rf /",
        "rm -rf ~",
        "format *",
        "del /s *",
        "git push --force*",
        "curl * | *sh",
        "iwr * | iex",
        "Invoke-Expression*",
    ])
    sensitive_file_patterns: list[str] = field(default_factory=lambda: [
        ".env",
        ".env.*",
        "*credentials*",
        "*secret*",
        "id_rsa",
        "*.pem",
    ])
    ask_shell_patterns: list[str] = field(default_factory=lambda: [
        "git push*",
        "pip install*",
        "npm install*",
        "npm publish*",
        "docker push*",
        "kubectl *",
        "terraform apply*",
    ])
    allowed_roots: list[str] = field(default_factory=list)


@dataclass
class ControllerConfig:
    enabled: bool = True
    headless_output_format: str = "stream-json"
    max_turns: int = 20
    auto_create_branch: bool = False
    branch_prefix: str = "claugram/"
    # Attach the MCP server to controller (headless) runs. Off by default is
    # safer for unattended runs because it prevents Claude from blocking on
    # ask_user_question with no interactive terminal; hooks still notify.
    attach_mcp: bool = True
    # IDLE timeout: kill the claude process only if it produces NO output for
    # this many seconds (i.e. it's genuinely stuck, e.g. an MCP handshake hang).
    # A long but productive run keeps streaming and is never killed. 0 disables.
    idle_timeout_sec: int = 86400  # 1 day; a long single turn can be silent for minutes


@dataclass
class Config:
    version: int = 1
    project_name: str = ""
    project_root: str = ""
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    approval: ApprovalConfig = field(default_factory=ApprovalConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    controller: ControllerConfig = field(default_factory=ControllerConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        def section(model, key):
            raw = data.get(key) or {}
            known = {f for f in model.__dataclass_fields__}
            return model(**{k: v for k, v in raw.items() if k in known})

        return cls(
            version=int(data.get("version", 1)),
            project_name=str(data.get("project_name", "")),
            project_root=str(data.get("project_root", "")),
            telegram=section(TelegramConfig, "telegram"),
            schedule=section(ScheduleConfig, "schedule"),
            claude=section(ClaudeConfig, "claude"),
            notifications=section(NotificationsConfig, "notifications"),
            approval=section(ApprovalConfig, "approval"),
            security=section(SecurityConfig, "security"),
            controller=section(ControllerConfig, "controller"),
        )
