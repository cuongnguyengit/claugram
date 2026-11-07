import json
import tomllib

from claugram.config import Config, write_config, load_config
from claugram.config.models import TelegramConfig
from claugram.claude.settings_patch import patch_settings, unpatch_settings, HOOK_CMD_PREFIX
from claugram.claude.claude_md_patch import patch_claude_md, unpatch_claude_md, BEGIN


def test_config_roundtrip(tmp_path):
    cfg = Config()
    cfg.project_name = "demo"
    cfg.project_root = str(tmp_path)
    cfg.telegram = TelegramConfig(bot_token_ref="user:default",
                                  allowed_chat_ids=[123, 456])
    write_config(tmp_path, cfg)
    loaded = load_config(tmp_path)
    assert loaded.project_name == "demo"
    assert loaded.telegram.allowed_chat_ids == [123, 456]
    # ensure it is valid TOML on disk
    with (tmp_path / ".claugram" / "config.toml").open("rb") as fh:
        tomllib.load(fh)


def test_nested_toml_and_token_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUGRAM_HOME", str(tmp_path / "home"))
    from claugram.config import _toml
    text = _toml.dumps({"version": 1, "tokens": {"default": {"bot_token": "abc:xyz"}}})
    data = tomllib.loads(text)
    assert data["tokens"]["default"]["bot_token"] == "abc:xyz"

    from claugram.config.writer import save_bot_token
    from claugram.config import resolve_bot_token
    save_bot_token("default", "123:secret")
    assert resolve_bot_token("user:default") == "123:secret"


def test_settings_patch_idempotent(tmp_path):
    patch_settings(tmp_path)
    patch_settings(tmp_path)  # twice -> no duplicates
    data = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
    post = data["hooks"]["PostToolUse"]
    claugram_entries = [e for e in post
                        if any(HOOK_CMD_PREFIX in h["command"] for h in e["hooks"])]
    assert len(claugram_entries) == 1
    # permission hooks must match ALL tools so every prompt routes to Telegram
    for event in ("PreToolUse", "PermissionRequest"):
        entry = data["hooks"][event][0]
        assert entry["matcher"] == "*", event
    unpatch_settings(tmp_path)
    data2 = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
    assert "hooks" not in data2 or not data2["hooks"]


def test_claude_md_patch_idempotent(tmp_path):
    patch_claude_md(tmp_path)
    patch_claude_md(tmp_path)
    content = (tmp_path / "CLAUDE.md").read_text()
    assert content.count(BEGIN) == 1
    unpatch_claude_md(tmp_path)
    assert BEGIN not in (tmp_path / "CLAUDE.md").read_text()
