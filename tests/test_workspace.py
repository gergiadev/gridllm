from pathlib import Path

import pytest
from mcp import MCPError

from gridllm.GridMCPServer.workspace import (
    isIgnored,
    readLines,
    relPath,
    resolveSafe,
    walk,
    writeAtomic,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = (tmp_path / "ws").resolve()
    (root / "src").mkdir(parents=True)
    (root / "src" / "vm.c").write_text("int x;\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("alias", ["", ".", "./", "/", "*", "**"])
def test_root_aliases_resolve_to_the_workspace(workspace, alias):
    assert resolveSafe(workspace, alias) == workspace


def test_equivalent_spellings_resolve_to_one_path(workspace):
    target = workspace / "src" / "vm.c"
    for spelling in ["src/vm.c", "./src/vm.c", str(target), "src/../src/vm.c"]:
        assert resolveSafe(workspace, spelling) == target


def test_parent_traversal_is_refused(workspace):
    with pytest.raises(MCPError):
        resolveSafe(workspace, "../secret")


def test_symlink_pointing_outside_is_refused(workspace, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    (workspace / "link").symlink_to(outside)
    with pytest.raises(MCPError):
        resolveSafe(workspace, "link")


def test_relpath_falls_back_to_the_name_when_unrelated(workspace, tmp_path):
    assert relPath(workspace / "src" / "vm.c", workspace) == "src/vm.c"
    assert relPath(tmp_path / "elsewhere" / "x.c", workspace) == "x.c"


def test_isignored_matches_any_path_component(workspace):
    assert isIgnored(workspace / ".git" / "HEAD", workspace, (".git",))
    assert isIgnored(workspace / "a" / "__pycache__" / "m.pyc", workspace, ("__pycache__",))
    assert not isIgnored(workspace / "src" / "vm.c", workspace, (".git", "build"))


def test_write_atomic_creates_parents_and_leaves_no_temp_file(workspace):
    target = workspace / "deep" / "nested" / "out.txt"
    assert writeAtomic(target, "hello\n") == 6
    assert target.read_text(encoding="utf-8") == "hello\n"
    assert [p.name for p in target.parent.iterdir()] == ["out.txt"]


def test_write_atomic_replaces_existing_content(workspace):
    target = workspace / "src" / "vm.c"
    writeAtomic(target, "int y;\n")
    assert target.read_text(encoding="utf-8") == "int y;\n"


def test_write_atomic_keeps_the_mode_of_the_file_it_replaces(workspace):
    target = workspace / "run.sh"
    target.write_text("#!/bin/sh\n", encoding="utf-8")
    target.chmod(0o755)
    writeAtomic(target, "#!/bin/sh\necho hi\n")
    assert target.stat().st_mode & 0o777 == 0o755


def test_walk_does_not_descend_into_ignored_directories(workspace):
    (workspace / ".git" / "objects").mkdir(parents=True)
    (workspace / ".git" / "objects" / "blob").write_text("x", encoding="utf-8")
    found = [relPath(path, workspace) for path in walk(workspace, workspace, (".git",))]
    assert found == ["src", "src/vm.c"]


def test_read_lines_returns_the_window_and_the_total(workspace):
    target = workspace / "long.txt"
    target.write_text("".join(f"line{n}\n" for n in range(1, 11)), encoding="utf-8")
    assert readLines(target, 2, 2) == (["line3", "line4"], 10)
    assert readLines(target, 8, 0) == (["line9", "line10"], 10)
