from pathlib import Path

import pytest
from mcp import MCPError

from gridllm.GridMCPServer.workspace import isIgnored, relPath, resolveSafe, writeAtomic


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
