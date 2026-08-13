from mcp import Client, MCPError

from ..events import KIND_TOOL_CALL, KIND_TOOL_RESULT, EventBus
from ..GridMCPServer.permissions import WRITE_TOOLS
from ..logging_setup import Tracer, traced


class Toolbox:

    def __init__(self, url: str, trace: Tracer, agent: str | None = None, bus: EventBus | None = None):
        self.url = url
        self.trace = trace
        self.agent = agent
        self.bus = bus
        self.touched: set[str] = set()

    @traced
    async def schemas(self) -> list[dict]:
        async with Client(self.url) as client:
            result = await client.list_tools()

        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.input_schema,
                },
            }
            for tool in result.tools
        ]

    @traced
    async def call(self, name: str, arguments: dict) -> str:
        EventBus.emit_to(self.bus, KIND_TOOL_CALL, {"name": name, "arguments": arguments}, self.agent)
        self.trace.tool(name, arguments)
        async with Client(self.url) as client:
            try:
                result = await client.call_tool(name, arguments)
            except MCPError as error:
                return self._failed(name, error)

            if result.is_error:
                return self._failed(name, result.content)

            content = "\n".join(block.text for block in result.content if hasattr(block, "text"))
            if name in WRITE_TOOLS and arguments.get("path"):
                self.touched.add(str(arguments["path"]))
            self.trace.result(name, content)
            EventBus.emit_to(self.bus, KIND_TOOL_RESULT, {"name": name, "content": content[:2000]}, self.agent)
            return content

    def _failed(self, name: str, detail) -> str:
        message = f"Tool execution error: {detail}"
        self.trace.result(name, message, error=True)
        EventBus.emit_to(self.bus, KIND_TOOL_RESULT, {"name": name, "content": message, "error": True}, self.agent)
        return message
