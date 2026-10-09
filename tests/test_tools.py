import asyncio
import logging
from pathlib import Path

import pytest
from mcp import MCPError

from gridllm.GridMCPServer.permissions import CURRENT_ACCESS, WriteScope
from gridllm.GridMCPServer.readers import choose_reader
from gridllm.GridMCPServer.sandbox import Sandbox
from gridllm.GridMCPServer.tools import Tools, capped


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = (tmp_path / "ws").resolve()
    root.mkdir()
    (root / "vm.c").write_text("\n".join(f"line{n}" for n in range(1, 11)) + "\n", encoding="utf-8")
    return root


@pytest.fixture
def tools(workspace: Path) -> Tools:
    logger = logging.getLogger("tests.tools")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return Tools(
        workspace,
        choose_reader(logger, ignore=()),
        maxBytes=1_000_000,
        shellTimeout=2,
        ignore=(),
        logger=logger,
        sandbox=Sandbox(workspace),
        scope=WriteScope(workspace),
    )


async def test_read_file_returns_the_requested_window(tools):
    assert await tools.read_file("vm.c", offset=3, limit=2) == "line3\nline4"


async def test_read_file_reports_the_range_it_was_asked_for(tools):
    message = await tools.read_file("vm.c", offset=50, limit=3)
    assert "lines 50-52 out of range" in message
    assert "file has 10 lines" in message


async def test_read_file_without_a_window_returns_everything(tools):
    assert (await tools.read_file("vm.c")).count("\n") == 10


async def test_reading_a_directory_is_refused(tools):
    with pytest.raises(MCPError):
        await tools.read_file(".")


async def test_editing_a_directory_reports_a_clean_error(tools):
    with pytest.raises(MCPError, match="is a directory"):
        await tools.edit_file(".", "a", "b")


async def test_editing_a_missing_file_reports_a_clean_error(tools):
    with pytest.raises(MCPError, match="file not found"):
        await tools.edit_file("nope.c", "a", "b")


async def test_listing_a_missing_directory_reports_a_clean_error(tools):
    with pytest.raises(MCPError, match="no such directory"):
        await tools.list_files("nope")


async def test_stat_of_a_missing_file_reports_a_clean_error(tools):
    with pytest.raises(MCPError, match="file not found"):
        await tools.stat("nope.c")


async def test_edit_file_requires_a_unique_match(tools, workspace):
    (workspace / "dup.c").write_text("x\nx\n", encoding="utf-8")
    with pytest.raises(MCPError, match="occurs 2 times"):
        await tools.edit_file("dup.c", "x", "y")


async def test_shell_timeout_reaps_the_process(tools, workspace):
    marker = workspace / "still_running.txt"
    with pytest.raises(MCPError, match="timed out"):
        await tools.shell(f"sleep 5 && touch {marker}")
    await asyncio.sleep(4)
    assert not marker.exists(), "the timed-out command outlived its timeout"


async def test_read_write_shell_runs_in_the_real_workspace(tools, workspace):
    token = CURRENT_ACCESS.set("rw")
    try:
        await tools.shell("touch made_here.txt")
    finally:
        CURRENT_ACCESS.reset(token)
    assert (workspace / "made_here.txt").exists()


async def test_read_only_shell_cannot_reach_the_workspace(tools, workspace):
    try:
        await tools.shell("touch not_here.txt")
        assert not (workspace / "not_here.txt").exists()
    finally:
        tools.sandbox.remove()


async def test_shell_warns_about_a_creation_outside_the_scope(tools, workspace):
    tools.scope.allow(["vm.c"])
    token = CURRENT_ACCESS.set("rw")
    try:
        output = await tools.shell("touch stray.c")
    finally:
        CURRENT_ACCESS.reset(token)
    assert "WARNING" in output
    assert "stray.c" in output


async def test_shell_warns_about_a_deletion_outside_the_scope(tools, workspace):
    (workspace / "victim.c").write_text("int v;\n", encoding="utf-8")
    tools.scope.allow(["vm.c"])
    token = CURRENT_ACCESS.set("rw")
    try:
        output = await tools.shell("rm victim.c")
    finally:
        CURRENT_ACCESS.reset(token)
    assert "WARNING" in output
    assert "victim.c" in output


async def test_shell_stays_quiet_for_a_change_inside_the_scope(tools):
    tools.scope.allow(["vm.c"])
    token = CURRENT_ACCESS.set("rw")
    try:
        output = await tools.shell("echo touched >> vm.c")
    finally:
        CURRENT_ACCESS.reset(token)
    assert "WARNING" not in output


async def test_capped_truncates_and_says_so():
    async def long_output() -> str:
        return "x" * 100

    assert "output truncated" in await capped(long_output, 10)()
    assert await capped(long_output, 0)() == "x" * 100


def test_capped_keeps_the_wrapped_signature():
    import inspect

    wrapped = capped(Tools.read_file, 10)
    assert wrapped.__name__ == "read_file"
    assert "offset" in inspect.signature(wrapped).parameters


async def test_a_window_can_be_read_from_a_file_over_the_size_limit(tools, workspace):
    (workspace / "huge.c").write_text("x" * 99 + "\n" + "wanted\n" + "y" * 1_000_000, encoding="utf-8")
    with pytest.raises(MCPError, match="too large"):
        await tools.read_file("huge.c")
    assert await tools.read_file("huge.c", offset=2, limit=1) == "wanted"


async def test_symbols_of_a_missing_path_report_a_clean_error(tools):
    with pytest.raises(MCPError, match="no such file or directory"):
        await tools.list_symbols("nope")


async def test_shell_does_not_inherit_the_api_keys(tools, monkeypatch):
    monkeypatch.setenv("GRID_TEST_KEY", "sk-secret")
    monkeypatch.setenv("GRID_TEST_PLAIN", "visible")
    tools.secretEnv = frozenset({"GRID_TEST_KEY"})
    try:
        output = await tools.shell("echo [$GRID_TEST_KEY] [$GRID_TEST_PLAIN]")
    finally:
        tools.sandbox.remove()
    assert "[] [visible]" in output


async def test_git_tools_report_when_there_is_no_repository(tools):
    assert "not a git repository" in (await tools.git_diff()).lower()
