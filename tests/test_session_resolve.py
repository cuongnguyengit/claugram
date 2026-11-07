from claugram.storage import Store
from claugram.claude.session import resolve_session, remember_session
from claugram.claude.cli import build_headless_args


def test_headless_args_strict_mcp_and_flags():
    args = build_headless_args("hi", mcp_config="x.json", session_id="s1", max_turns=8)
    assert "--strict-mcp-config" in args           # don't inherit heavy user MCP servers
    assert "--mcp-config" in args and "x.json" in args
    assert args[args.index("--resume") + 1] == "s1"
    # no mcp_config -> no strict flag
    assert "--strict-mcp-config" not in build_headless_args("hi")


def test_code_is_fresh_continue_resumes(tmp_path):
    s = Store(tmp_path / "s.sqlite3")
    pid = s.upsert_project("demo", str(tmp_path))

    # no history yet: /code is fresh, /continue falls back to --continue
    assert resolve_session(s, pid, "code") == {"session_id": None, "continue_last": False}
    assert resolve_session(s, pid, "continue") == {"session_id": None, "continue_last": True}

    # after a session is remembered
    remember_session(s, pid, "sess-abc")
    assert resolve_session(s, pid, "code") == {"session_id": None, "continue_last": False}
    assert resolve_session(s, pid, "continue") == {"session_id": "sess-abc", "continue_last": False}

    # explicit selection wins for every command
    s.set_active_session(pid, "sess-xyz")
    for cmd in ("code", "ask", "continue"):
        assert resolve_session(s, pid, cmd) == {"session_id": "sess-xyz", "continue_last": False}
    s.close()
