"""Read-only project views (ls / cat / grep / tree) — traversal-safe, capped."""

from claugram import fileview


def _mk(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "import os\n\ndef run():\n    return 42\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\nhello world\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "junk").write_text("x", encoding="utf-8")
    return tmp_path


def test_ls_lists_and_marks_skipped(tmp_path):
    _mk(tmp_path)
    out = fileview.ls(tmp_path)
    assert "src/" in out and "README.md" in out
    assert ".git/  …" in out  # skipped dir is shown but flagged


def test_ls_subdir_and_file(tmp_path):
    _mk(tmp_path)
    assert "app.py" in fileview.ls(tmp_path, "src")
    assert "📄 src" in fileview.ls(tmp_path, "src/app.py")


def test_cat_with_range(tmp_path):
    _mk(tmp_path)
    out = fileview.cat(tmp_path, "src/app.py", "3-4")
    assert "3\tdef run():" in out
    assert "return 42" in out
    assert "lines 3-4 of 4" in out


def test_cat_missing_and_usage(tmp_path):
    _mk(tmp_path)
    assert "Not a file" in fileview.cat(tmp_path, "nope.py")
    assert "Usage" in fileview.cat(tmp_path, "")


def test_grep_reports_file_and_line(tmp_path):
    _mk(tmp_path)
    out = fileview.grep(tmp_path, "def run")
    assert "src" in out and "app.py:3:" in out
    assert "No matches" in fileview.grep(tmp_path, "zzz-not-there")


def test_grep_skips_git(tmp_path):
    _mk(tmp_path)
    # content only exists inside .git -> must not be searched
    (tmp_path / ".git" / "secret.txt").write_text("NEEDLE123", encoding="utf-8")
    assert "No matches" in fileview.grep(tmp_path, "NEEDLE123")


def test_traversal_is_blocked(tmp_path):
    _mk(tmp_path)
    assert "escapes project root" in fileview.ls(tmp_path, "../..")
    assert "escapes project root" in fileview.cat(tmp_path, "../../etc/hosts")


def test_bad_regex(tmp_path):
    _mk(tmp_path)
    assert "Bad regex" in fileview.grep(tmp_path, "(")


def test_pipeline_cat_grep_head(tmp_path):
    _mk(tmp_path)
    out = fileview.pipeline(tmp_path, "cat src/app.py | grep 'def ' | head 1")
    assert "def run():" in out
    assert "import os" not in out  # filtered out by grep


def test_pipeline_ls_grep(tmp_path):
    _mk(tmp_path)
    out = fileview.pipeline(tmp_path, "ls | grep README")
    assert "README.md" in out and "src/" not in out


def test_pipeline_wc_and_nl(tmp_path):
    _mk(tmp_path)
    assert "4 lines" in fileview.pipeline(tmp_path, "cat src/app.py | wc")
    assert "1\t" in fileview.pipeline(tmp_path, "ls | nl")


def test_pipeline_unknown_filter_and_bad_source(tmp_path):
    _mk(tmp_path)
    assert "Unknown filter" in fileview.pipeline(tmp_path, "ls | frobnicate")
    assert "must start with" in fileview.pipeline(tmp_path, "status | grep x")


def test_pipeline_traversal_blocked(tmp_path):
    _mk(tmp_path)
    assert "escapes project root" in fileview.pipeline(tmp_path, "cat ../../x | grep y")
