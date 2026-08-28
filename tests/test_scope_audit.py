from pathlib import Path

import pytest

from gridllm.GridMCPServer.permissions import WriteScope
from gridllm.GridMCPServer.sandbox import modified, snapshot


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "a.c").write_text("int a;\n", encoding="utf-8")
    (tmp_path / "b.c").write_text("int b;\n", encoding="utf-8")
    return tmp_path


def test_modified_reports_a_changed_file(workspace):
    before = snapshot(workspace, ())
    (workspace / "a.c").write_text("int a = 1;\n", encoding="utf-8")
    assert modified(before, snapshot(workspace, ())) == [(workspace / "a.c").as_posix()]


def test_modified_reports_a_created_file(workspace):
    before = snapshot(workspace, ())
    (workspace / "new.c").write_text("int n;\n", encoding="utf-8")
    assert modified(before, snapshot(workspace, ())) == [(workspace / "new.c").as_posix()]


def test_modified_reports_a_deleted_file(workspace):
    before = snapshot(workspace, ())
    (workspace / "b.c").unlink()
    assert modified(before, snapshot(workspace, ())) == [(workspace / "b.c").as_posix()]


def test_modified_ignores_build_artifacts(workspace):
    before = snapshot(workspace, ())
    (workspace / "a.o").write_bytes(b"\x00")
    (workspace / "libx.so").write_bytes(b"\x00")
    assert modified(before, snapshot(workspace, ())) == []


def test_snapshot_honours_the_ignore_patterns(workspace):
    (workspace / ".git").mkdir()
    before = snapshot(workspace, (".git",))
    (workspace / ".git" / "HEAD").write_text("ref\n", encoding="utf-8")
    assert modified(before, snapshot(workspace, (".git",))) == []


def test_untracked_creation_is_visible_without_git(workspace):
    assert not (workspace / ".git").exists()
    before = snapshot(workspace, ())
    (workspace / "generated.c").write_text("int g;\n", encoding="utf-8")
    assert modified(before, snapshot(workspace, ()))


def test_scope_permits_only_the_listed_files(workspace):
    scope = WriteScope(workspace)
    scope.allow(["a.c"])
    assert scope.permits("a.c")
    assert scope.permits("./a.c")
    assert scope.permits(str(workspace / "a.c"))
    assert not scope.permits("b.c")
    assert not scope.permits("../outside.c")


def test_cleared_scope_permits_everything(workspace):
    scope = WriteScope(workspace)
    scope.allow(["a.c"])
    scope.clear()
    assert scope.permits("b.c")


def test_changes_outside_the_scope_are_the_ones_reported(workspace):
    scope = WriteScope(workspace)
    scope.allow(["a.c"])
    before = snapshot(workspace, ())
    (workspace / "a.c").write_text("int a = 1;\n", encoding="utf-8")
    (workspace / "created.c").write_text("int c;\n", encoding="utf-8")
    (workspace / "b.c").unlink()

    offending = [p for p in modified(before, snapshot(workspace, ())) if not scope.permits(p)]
    assert sorted(Path(p).name for p in offending) == ["b.c", "created.c"]
