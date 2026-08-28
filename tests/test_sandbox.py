from pathlib import Path

import pytest

from gridllm.GridMCPServer.sandbox import Sandbox


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return root


async def test_each_agent_gets_its_own_copy(workspace):
    sandbox = Sandbox(workspace, ignore=(".git",))
    try:
        first = await sandbox.path("thinker-1")
        second = await sandbox.path("thinker-2")
        assert first != second
        assert (first / "main.c").exists()
        assert (second / "main.c").exists()
    finally:
        sandbox.remove()


async def test_one_agent_does_not_see_what_another_wrote(workspace):
    sandbox = Sandbox(workspace, ignore=(".git",))
    try:
        first = await sandbox.path("thinker-1")
        second = await sandbox.path("thinker-2")
        (first / "scratch.txt").write_text("mine\n", encoding="utf-8")
        assert not (second / "scratch.txt").exists()
    finally:
        sandbox.remove()


async def test_the_same_agent_keeps_its_copy_between_commands(workspace):
    sandbox = Sandbox(workspace, ignore=(".git",))
    try:
        first = await sandbox.path("thinker-1")
        (first / "built.o").write_bytes(b"\x00")
        again = await sandbox.path("thinker-1")
        assert again == first
        assert (again / "built.o").exists()
    finally:
        sandbox.remove()


async def test_writing_in_a_copy_never_touches_the_workspace(workspace):
    sandbox = Sandbox(workspace, ignore=(".git",))
    try:
        root = await sandbox.path("thinker-1")
        (root / "main.c").write_text("broken\n", encoding="utf-8")
        assert (workspace / "main.c").read_text(encoding="utf-8").startswith("int main")
    finally:
        sandbox.remove()


async def test_invalidate_drops_every_copy(workspace):
    sandbox = Sandbox(workspace, ignore=(".git",))
    first = await sandbox.path("thinker-1")
    second = await sandbox.path("thinker-2")
    await sandbox.invalidate()
    assert not first.exists()
    assert not second.exists()
    assert sandbox.roots == {}


async def test_ignored_paths_stay_out_of_the_copy(workspace):
    sandbox = Sandbox(workspace, ignore=(".git",))
    try:
        root = await sandbox.path("thinker-1")
        assert not (root / ".git").exists()
    finally:
        sandbox.remove()


async def test_remove_is_safe_to_call_twice(workspace):
    sandbox = Sandbox(workspace, ignore=(".git",))
    await sandbox.path("thinker-1")
    sandbox.remove()
    sandbox.remove()
    assert sandbox.roots == {}
