from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from pathlib import Path
from urllib.parse import parse_qs

from mcp import MCPError
from mcp.types import INVALID_PARAMS
from pydantic import BaseModel

from .workspace import resolveSafe

DEFAULT_ACCESS = "r"

READ_WRITE = "rw"

WRITE_TOOLS = frozenset({"write_file", "edit_file"})


class WriteScope:

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.allowed: frozenset[str] | None = None

    def allow(self, paths: Iterable[str]) -> None:
        self.allowed = frozenset(resolved for resolved in (self._resolve(path) for path in paths) if resolved)

    def clear(self) -> None:
        self.allowed = None

    def permits(self, path: str) -> bool:
        if self.allowed is None:
            return True
        resolved = self._resolve(path)
        return resolved is not None and resolved in self.allowed

    def _resolve(self, path: str) -> str | None:
        try:
            return str(resolveSafe(self.workspace, str(path)))
        except MCPError:
            return None


class PermissionFilter:

    def __init__(
        self,
        access_from_agent: Mapping[str, str],
        write_tools: set[str],
        logger: logging.Logger,
        scope: WriteScope | None = None,
    ) -> None:
        self.access_from_agent = dict(access_from_agent)
        self.write_tools = write_tools
        self.logger = logger
        self.scope = scope

    def _resolve(self, ctx) -> tuple[str, str]:
        request = getattr(ctx, "request", None)
        if request is None:
            self.logger.warning("request without HTTP context: applying '%s'", DEFAULT_ACCESS)
            return "<unknown>", DEFAULT_ACCESS

        agents = parse_qs(request.url.query).get("agent", [])
        if not agents:
            self.logger.warning("connection without 'agent' parameter: applying '%s'", DEFAULT_ACCESS)
            return "<anonymous>", DEFAULT_ACCESS

        agent = agents[0]
        access = self.access_from_agent.get(agent)
        if access is None:
            self.logger.warning("agent '%s' not in config: applying '%s'", agent, DEFAULT_ACCESS)
            return agent, DEFAULT_ACCESS

        return agent, access

    async def __call__(self, ctx, call_next):
        if ctx.method not in ("tools/list", "tools/call"):
            return await call_next(ctx)

        agent, access = self._resolve(ctx)

        if ctx.method == "tools/call":
            params = ctx.params or {}
            name = params.get("name")
            if name in self.write_tools:
                if access != READ_WRITE:
                    self.logger.warning("denied '%s' to agent '%s' (access '%s')", name, agent, access)
                    raise MCPError(
                        INVALID_PARAMS,
                        f"tool '{name}' not available: the session is read-only",
                    )
                self._check_scope(agent, name, params.get("arguments") or {})
            return await call_next(ctx)

        result = await call_next(ctx)
        if access == READ_WRITE:
            return result
        return self._strip_write_tools(result, agent)

    def _check_scope(self, agent: str, name: str, arguments: Mapping) -> None:
        if self.scope is None:
            return

        path = arguments.get("path")
        if path is None or self.scope.permits(path):
            return

        self.logger.warning("denied '%s' on '%s' to agent '%s': outside the verdict scope", name, path, agent)
        raise MCPError(
            INVALID_PARAMS,
            f"'{path}' is not among the files the verdict allows you to write",
        )

    @staticmethod
    def _tool_name(tool) -> str:
        return tool["name"] if isinstance(tool, dict) else tool.name

    def _strip_write_tools(self, result, agent: str):
        if isinstance(result, BaseModel):
            exposed = [t for t in result.tools if self._tool_name(t) not in self.write_tools]
            result.tools = exposed
        elif isinstance(result, dict) and "tools" in result:
            exposed = [t for t in result["tools"] if self._tool_name(t) not in self.write_tools]
            result["tools"] = exposed
        else:
            return result

        self.logger.info("tools/list for '%s': %d tools exposed", agent, len(exposed))
        return result
