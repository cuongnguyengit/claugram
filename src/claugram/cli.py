"""claugram command-line interface (Typer)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer

# Windows consoles default to cp1252 and cannot encode the emoji we print.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

from . import __version__
from .config import (
    Config, paths, write_config, save_bot_token, resolve_bot_token,
    try_load_config,
)
from .config.models import TelegramConfig

app = typer.Typer(
    help="Claude Code <-> Telegram bridge.",
    no_args_is_help=True,
    add_completion=False,
)


def _echo(msg: str = "") -> None:
    typer.echo(msg)


def _resolve_project(project: Optional[str]) -> Path:
    if project:
        return Path(project).resolve()
    return paths.detect_project_root()


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #
@app.command()
def init(
    project: Optional[str] = typer.Option(None, help="Project root (default: detect)."),
    bot_token: Optional[str] = typer.Option(
        None, help="Bot token (or 'env:VAR' / 'raw:<token>'). "
                   "Omit to reuse the token already saved for the bot."),
    chat_id: Optional[int] = typer.Option(
        None, help="Your Telegram chat id. Omit to auto-detect from /start "
                   "(needs no bot running)."),
    mode: str = typer.Option("interactive", help="interactive | headless"),
    transport: str = typer.Option("telegram", help="Message transport: telegram | fake."),
    install_service: bool = typer.Option(False, help="Install a login service."),
    dry_run: bool = typer.Option(False, help="Show actions without writing."),
    force: bool = typer.Option(False, help="Overwrite existing config."),
) -> None:
    """Onboard claugram for the current project."""
    from .claude import cli as claude_cli
    from .claude.settings_patch import patch_settings
    from .claude.claude_md_patch import patch_claude_md
    from .claude.mcp_config import write_mcp_config
    from .telegram import TelegramClient, resolve_chat_id, token_has_active_poller

    root = _resolve_project(project)
    interactive = mode != "headless" and sys.stdin.isatty()
    _echo(f"Claugram setup for: {root}\n")

    existing = try_load_config(root)
    if existing and not force and not dry_run:
        _echo("A claugram config already exists here. Use --force to overwrite.")
        raise typer.Exit(1)

    # Step 1: claude CLI
    _echo("Step 1/8: Check Claude Code")
    exe = claude_cli.find_claude()
    if exe:
        _echo(f"  claude found: {exe} ({claude_cli.claude_version()})")
    else:
        _echo("  ⚠️  claude not found on PATH (interactive/hook features need it).")

    # Step 2: git
    _echo("Step 2/8: Check Git")
    _echo(f"  git repo: {'yes' if (root / '.git').exists() else 'no (optional)'}")

    # Step 3: bot token
    _echo("Step 3/8: Configure Telegram bot")
    token_ref = "user:default"
    resolved_token: Optional[str] = None
    token_is_new = False  # only persist/announce a token the user just supplied
    if bot_token and bot_token.startswith("env:"):
        token_ref = bot_token
        resolved_token = resolve_bot_token(bot_token)
    elif bot_token:
        resolved_token = bot_token[4:] if bot_token.startswith("raw:") else bot_token
        token_is_new = True
    else:
        # No --bot-token: reuse the token already saved under user:default so
        # re-running init (e.g. for a new project) doesn't re-prompt.
        resolved_token = resolve_bot_token("user:default")
        if resolved_token:
            _echo("  Using saved token from user credentials.")
        elif interactive:
            resolved_token = typer.prompt("  Paste bot token", hide_input=True).strip()
            token_is_new = True
    if token_ref == "user:default" and resolved_token and token_is_new and not dry_run:
        save_bot_token("default", resolved_token)
        _echo("  Saved token to user credentials.")
    if not resolved_token:
        _echo("  ⚠️  No token provided; set one later in credentials.toml.")

    # verify token
    bot_username = None
    bot_running: Optional[bool] = None  # is a bot/hub already polling this token?
    if resolved_token:
        try:
            client = TelegramClient(resolved_token)
            me = client.get_me()
            bot_username = me.get("username")
            _echo(f"  Bot OK: @{bot_username}")
            bot_running = token_has_active_poller(client)
            if bot_running:
                _echo("  A claugram bot/hub is already running on this token.")
            # register the "/" autocomplete menu now so hints show immediately
            if not dry_run:
                from .telegram.polling import BOT_COMMANDS
                try:
                    client.set_my_commands(BOT_COMMANDS)
                    _echo("  Registered command menu (/ autocomplete).")
                except Exception:
                    pass  # non-fatal; the bot re-registers on startup
        except Exception as exc:
            _echo(f"  ⚠️  Could not verify token: {exc}")

    # Step 4: chat id
    _echo("Step 4/8: Resolve chat ID")
    resolved_chat = chat_id
    if resolved_chat is None and resolved_token and interactive and bot_running:
        # auto-detect can't work while a bot holds the getUpdates slot
        _echo("  ⚠️  Skipping /start auto-detect: a bot/hub is already polling "
              "this token.")
        _echo("      Re-run with --chat-id <id>, or stop the bot first.")
    elif resolved_chat is None and resolved_token and interactive:
        _echo(f"  Auto-detecting: send /start to @{bot_username or 'your bot'} now.")
        typer.prompt("  Press Enter after sending", default="", show_default=False)
        try:
            resolved_chat = resolve_chat_id(TelegramClient(resolved_token), wait_sec=30)
        except Exception as exc:
            _echo(f"  ⚠️  {exc}")
    if resolved_chat:
        _echo(f"  Using chat_id: {resolved_chat}")
    else:
        _echo("  ⚠️  No chat_id resolved; set allowed_chat_ids in config later.")

    # Step 5: write config
    _echo("Step 5/8: Write project config")
    config = existing or Config()
    if not existing:
        # Fresh project: enforce the configured quiet-hours window by default.
        # Otherwise init writes active_window/active_days but leaves the master
        # switch respect_schedule=false, so the window is inert and forwarding
        # runs 24/7 — a foot-gun that repeatedly surprised users (bug-030,
        # bug-044). Opt out for 24/7: set [schedule] respect_schedule = false.
        config.schedule.respect_schedule = True
    config.project_name = config.project_name or root.name
    config.project_root = str(root)
    config.telegram = TelegramConfig(
        bot_token_ref=token_ref,
        allowed_chat_ids=[int(resolved_chat)] if resolved_chat else
        config.telegram.allowed_chat_ids,
        polling_timeout_sec=30,
        parse_mode="Markdown",
        transport=transport,
    )
    if not dry_run:
        p = write_config(root, config)
        _echo(f"  Created {p}")
        # register in the shared store so /projects (and hub) see it immediately,
        # without having to build a Runtime first. Same key (resolved root) as
        # Runtime.upsert_project, so the project_id is stable.
        from .storage import Store
        st = Store()
        try:
            st.upsert_project(config.project_name, str(root.resolve()))
        finally:
            st.close()
        _echo("  Registered project (visible in /projects).")
    else:
        _echo("  (dry-run) would write .claugram/config.toml")

    # Step 6: MCP config
    _echo("Step 6/8: Configure Claude MCP")
    mcp_path = write_mcp_config(root, config.claude.mcp_server_name, dry_run=dry_run)
    _echo(f"  {'(dry-run) ' if dry_run else ''}{mcp_path}")

    # Step 7: settings (hooks + auto-injected env)
    _echo("Step 7/8: Patch Claude settings")
    extra_env = {"CLAUGRAM_TRANSPORT": "fake"} if transport == "fake" else None
    sp, _ = patch_settings(root, dry_run=dry_run, extra_env=extra_env)
    _echo(f"  {'(dry-run) ' if dry_run else ''}{sp} (hooks + env: CLAUGRAM_PROJECT)")

    # Step 8: CLAUDE.md
    _echo("Step 8/8: Patch CLAUDE.md")
    cm = patch_claude_md(root, dry_run=dry_run)
    _echo(f"  {'(dry-run) ' if dry_run else ''}{cm}")

    # test message
    if resolved_token and resolved_chat and not dry_run:
        do_test = not interactive or typer.confirm("\nSend a test message now?",
                                                    default=True)
        if do_test:
            try:
                TelegramClient(resolved_token).send_message(
                    int(resolved_chat),
                    "✅ Claugram is connected to this project.")
                _echo("  Sent test message.")
            except Exception as exc:
                _echo(f"  ⚠️  Test failed: {exc}")

    if install_service and not dry_run:
        from .service import install_service as _install
        ok, detail = _install(root, config.project_name)
        _echo(f"\nService: {'OK' if ok else 'FAILED'} — {detail}")

    _echo("\n✅ Claugram ready.\n")
    from .schedule import forwarding_status
    _echo(f"Forwarding window: {forwarding_status(config)}")
    _echo("  (outside these hours hooks stay silent; set [schedule] "
          "respect_schedule=false in .claugram/config.toml for 24/7)")
    if bot_running:
        # a bot/hub is already polling — this project is picked up live
        _echo(f"A bot is already running on @{bot_username or 'your bot'}, so this "
              "project is live now.")
        _echo("In Telegram: /projects, then /use " + f"{config.project_name}"
              ", then /code <task>. (/help for all commands.)")
    else:
        _echo("Next — start ONE bot (only one may poll the token at a time), then")
        _echo("drive everything from Telegram:")
        _echo("  claugram hub                  # manages ALL your projects; /use to switch")
        _echo("  claugram bot --project .      # or just this one")
        _echo("\nThen in Telegram: /projects, /use <name>, /code <task>, /help")
    _echo("\nAdd more projects anytime: claugram init --chat-id <id>  "
          "(no need to stop the bot).")
    _echo("\nOptional — let a LOCAL Claude session reach you on Telegram (it can ask")
    _echo("questions / request approvals while you're away). REQUIRES the bot above to")
    _echo("be running, since the bot is what delivers your replies back:")
    _echo(f"  claude --mcp-config {paths.project_mcp_config_path(root)}")
    _echo("  See docs/USAGE.vi.md → “Two ways to use claugram” for details.")


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #
@app.command()
def doctor(project: Optional[str] = typer.Option(None)) -> None:
    """Diagnose the claugram setup."""
    from .claude.doctor import run_checks
    root = _resolve_project(project)
    _echo(f"claugram doctor — {root}\n")
    failed = 0
    for check in run_checks(root):
        if check.ok:
            mark = "OK  "
        elif check.optional:
            mark = "WARN"
        else:
            mark = "FAIL"
            failed += 1
        _echo(f"[{mark}] {check.label}" + (f" — {check.detail}" if check.detail else ""))
    _echo("")
    if failed:
        _echo(f"{failed} check(s) failed.")
        raise typer.Exit(1)
    _echo("All required checks passed.")


# --------------------------------------------------------------------------- #
# mcp-server
# --------------------------------------------------------------------------- #
@app.command("mcp-server")
def mcp_server(project: Optional[str] = typer.Option(None)) -> None:
    """Run the MCP server (invoked by Claude Code)."""
    from .mcp.server import main as server_main
    root = _resolve_project(project)
    server_main(root)


# --------------------------------------------------------------------------- #
# bot / controller
# --------------------------------------------------------------------------- #
@app.command()
def bot(
    project: Optional[str] = typer.Option(
        None, help="Project to run as primary (default: detect)."),
) -> None:
    """Run the Telegram bot + controller for ONE project (only one bot may
    poll the token at a time; use `hub` to drive all registered projects)."""
    from .controller.daemon import run_daemon
    root = _resolve_project(project)
    run_daemon(root, enable_controller=True)


@app.command()
def controller(project: Optional[str] = typer.Option(None)) -> None:
    """Alias for `bot`; framed as the installable long-running service."""
    from .controller.daemon import run_daemon
    root = _resolve_project(project)
    run_daemon(root, enable_controller=True)


@app.command()
def hub(
    project: Optional[str] = typer.Option(
        None, help="Primary project for bot credentials; default = newest registered."),
) -> None:
    """Run one bot across ALL registered projects (switch with /use)."""
    from .controller.daemon import run_daemon
    root = Path(project).resolve() if project else None
    run_daemon(root, enable_controller=True)


# --------------------------------------------------------------------------- #
# hook
# --------------------------------------------------------------------------- #
@app.command()
def hook(event: str = typer.Argument(..., help="Hook event name.")) -> None:
    """Run a hook handler (invoked by Claude Code; reads JSON on stdin)."""
    from .hooks import HANDLERS
    handler = HANDLERS.get(event)
    if not handler:
        typer.echo(f"Unknown hook '{event}'. Known: {', '.join(HANDLERS)}", err=True)
        raise typer.Exit(2)
    handler()  # reads stdin, prints decision, exits 0


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
@app.command()
def status(project: Optional[str] = typer.Option(None)) -> None:
    """Show current claugram status for the project."""
    from .runtime import Runtime
    from .cli_helpers import status_lines
    root = _resolve_project(project)
    config = try_load_config(root)
    if not config:
        _echo("No claugram config here. Run `claugram init`.")
        raise typer.Exit(1)
    rt = Runtime(root, config)
    try:
        for line in status_lines(rt):
            _echo(line)
    finally:
        rt.close()


# --------------------------------------------------------------------------- #
# uninstall
# --------------------------------------------------------------------------- #
@app.command()
def uninstall(
    project: Optional[str] = typer.Option(None),
    keep_secrets: bool = typer.Option(False, help="Keep user credentials."),
    remove_service: bool = typer.Option(False, help="Remove the login service."),
) -> None:
    """Remove claugram integration from the project."""
    from .claude.settings_patch import unpatch_settings
    from .claude.claude_md_patch import unpatch_claude_md
    root = _resolve_project(project)
    config = try_load_config(root)

    sp = unpatch_settings(root)
    _echo(f"Removed hooks from {sp}" if sp else "No settings to clean.")
    cm = unpatch_claude_md(root)
    _echo(f"Removed managed block from {cm}" if cm else "No CLAUDE.md block.")

    for f in (paths.project_mcp_config_path(root), paths.project_config_path(root)):
        if f.exists():
            f.unlink()
            _echo(f"Deleted {f}")
    cfg_dir = paths.project_config_dir(root)
    if cfg_dir.exists() and not any(cfg_dir.iterdir()):
        cfg_dir.rmdir()

    if remove_service and config:
        from .service import remove_service as _remove
        ok, detail = _remove(root, config.project_name)
        _echo(f"Service: {detail}")

    if not keep_secrets:
        _echo("(User credentials kept; delete credentials.toml manually to remove.)")
    _echo("\nUninstalled.")


# --------------------------------------------------------------------------- #
# version
# --------------------------------------------------------------------------- #
@app.command()
def version() -> None:
    """Print the claugram version."""
    _echo(__version__)


if __name__ == "__main__":
    app()
