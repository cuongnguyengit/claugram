import json

from claugram.claude import sessions_disk


def test_slug_matches_claude_encoding():
    # Claude replaces every non-alphanumeric char with '-'. Drive-letter case may
    # differ (Path.resolve upper-cases it); session_dir() matches case-insensitively.
    assert sessions_disk.slug_for("d:\\Projects\\mini-claude-remote-control").lower() \
        == "d--projects-mini-claude-remote-control"


def test_list_and_resolve(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    # fake ~/.claude/projects/<slug>/<uuid>.jsonl
    fake_home = tmp_path / "home"
    monkeypatch.setattr(sessions_disk.Path, "home", staticmethod(lambda: fake_home))
    slug = sessions_disk.slug_for(proj)
    sdir = fake_home / ".claude" / "projects" / slug
    sdir.mkdir(parents=True)
    uuid = "abcd1234-0000-0000-0000-000000000000"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "fix the parser"}},
        {"type": "assistant", "message": {"role": "assistant",
                                          "content": [{"type": "text", "text": "ok"}]}},
    ]
    (sdir / f"{uuid}.jsonl").write_text(
        "\n".join(json.dumps(x) for x in lines), encoding="utf-8")

    found = sessions_disk.list_sessions(proj)
    assert len(found) == 1
    assert found[0].session_id == uuid
    assert "fix the parser" in found[0].preview
    assert sessions_disk.resolve_ref(proj, "1") == uuid
    assert sessions_disk.resolve_ref(proj, "abcd1234") == uuid
    assert sessions_disk.resolve_ref(proj, "nope") is None
