from types import SimpleNamespace

import pytest
from mcp import MCPError

from gridllm.GridMCPServer.permissions import WRITE_TOOLS, PermissionFilter, WriteScope

ACCESS = {"worker": "rw", "judge": "r"}


def _call(agent: str, tool: str, path: str = "vm.c") -> SimpleNamespace:
    return SimpleNamespace(
        method="tools/call",
        params={"name": tool, "arguments": {"path": path}},
        request=SimpleNamespace(url=SimpleNamespace(query=f"agent={agent}")),
    )


async def _served(ctx) -> str:
    return "served"


@pytest.fixture
def scope(tmp_path) -> WriteScope:
    return WriteScope(tmp_path.resolve())


@pytest.fixture
def permissions(quiet_logger, scope) -> PermissionFilter:
    return PermissionFilter(ACCESS, set(WRITE_TOOLS), quiet_logger, scope)


async def test_a_read_only_agent_is_refused_a_write_tool(permissions):
    with pytest.raises(MCPError, match="read-only"):
        await permissions(_call("judge", "write_file"), _served)


async def test_an_unknown_agent_is_read_only(permissions):
    with pytest.raises(MCPError, match="read-only"):
        await permissions(_call("stranger", "edit_file"), _served)


async def test_a_read_only_agent_keeps_the_read_tools(permissions):
    assert await permissions(_call("judge", "read_file"), _served) == "served"


async def test_the_worker_writes_only_inside_the_verdict_scope(permissions, scope):
    assert await permissions(_call("worker", "write_file"), _served) == "served"
    scope.allow(["other.c"])
    with pytest.raises(MCPError, match="not among the files"):
        await permissions(_call("worker", "write_file"), _served)
    assert await permissions(_call("worker", "write_file", "other.c"), _served) == "served"


async def test_write_tools_are_hidden_from_a_read_only_listing(permissions):
    async def listing(ctx) -> dict:
        return {"tools": [{"name": "read_file"}, {"name": "write_file"}, {"name": "edit_file"}]}

    ctx = SimpleNamespace(method="tools/list", request=SimpleNamespace(url=SimpleNamespace(query="agent=judge")))
    assert await permissions(ctx, listing) == {"tools": [{"name": "read_file"}]}
