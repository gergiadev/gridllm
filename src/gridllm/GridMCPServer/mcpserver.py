from collections.abc import Iterable, Mapping
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from ..logging_setup import get_logger, silence_third_party
from .permissions import WRITE_TOOLS, PermissionFilter, WriteScope
from .readers import DEFAULT_SUBPROCESS_TIMEOUT, choose_reader
from .tools import Tools, capped

DEFAULT_MAX_BYTES = 1_048_576

DEFAULT_MAX_TOOL_CHARS = 50_000

DEFAULT_IGNORE = (".git", ".gridllm", ".venv", "__pycache__", "node_modules", "build")

QUIET = "CRITICAL"


class GridMCPServer:

    def __init__(
        self,
        name: str,
        accessFromAgent: Mapping[str, str],
        workspace: str,
        maxBytes: int = DEFAULT_MAX_BYTES,
        subprocessTimeout: int = DEFAULT_SUBPROCESS_TIMEOUT,
        shellTimeout: int = 60,
        ignore: Iterable[str] = DEFAULT_IGNORE,
        maxToolChars: int = DEFAULT_MAX_TOOL_CHARS,
    ):
        self.workspace = Path(workspace).resolve()
        self.maxBytes = maxBytes
        self.subprocessTimeout = subprocessTimeout
        self.shellTimeout = shellTimeout
        self.ignore = tuple(ignore)
        self.maxToolChars = maxToolChars
        self.logger = get_logger(f"mcp.{name}")
        self.mcp = MCPServer(name, log_level=QUIET)
        silence_third_party()
        reader = choose_reader(self.logger, timeout=subprocessTimeout, ignore=self.ignore)
        self.tools = Tools(self.workspace, reader, maxBytes, shellTimeout, self.ignore, self.logger)
        self.writeTools = self._registerTools()
        if self.writeTools != set(WRITE_TOOLS):
            raise RuntimeError(f"registered write tools {sorted(self.writeTools)} differ from {sorted(WRITE_TOOLS)}")
        self.scope = WriteScope(self.workspace)
        self.mcp.middleware.append(PermissionFilter(accessFromAgent, self.writeTools, self.logger, self.scope))

    def _registerTools(self) -> set[str]:
        readTools = (
            self.tools.list_files,
            self.tools.read_file,
            self.tools.search_content,
            self.tools.stat,
            self.tools.list_symbols,
            self.tools.find_symbol,
            self.tools.get_symbol_body,
            self.tools.shell,
            self.tools.git_diff,
            self.tools.git_log,
            self.tools.git_blame,
        )
        writeTools = (
            self.tools.write_file,
            self.tools.edit_file,
        )

        for fn in readTools:
            self.mcp.tool(meta={"grid_write": False})(capped(fn, self.maxToolChars))
        for fn in writeTools:
            self.mcp.tool(meta={"grid_write": True})(capped(fn, self.maxToolChars))

        return {fn.__name__ for fn in writeTools}

    def run(self, transport: str = "streamable-http", **kwargs) -> None:
        silence_third_party()
        self.logger.info(
            "Server started (transport=%s, workspace=%s, maxBytes=%d, timeout=%ds)",
            transport,
            self.workspace,
            self.maxBytes,
            self.subprocessTimeout,
        )
        self.mcp.run(transport=transport, **kwargs)