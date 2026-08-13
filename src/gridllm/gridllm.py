import argparse
import asyncio
import shutil
import socket
import threading
import time

from dotenv import load_dotenv

from . import paths
from .compaction import Compactor
from .config import GridConfig, load_config
from .events import EventBus
from .GridMCPServer import GridMCPServer
from .LLMClient import AgentError, LLMClient, Toolbox
from .logging_setup import Tracer, get_logger, setup_logging, silence_third_party
from .orchestrator import Grid

LOG_FILE = "grid.log"


def _serve(server: GridMCPServer, config: GridConfig) -> None:
    server.run(transport="streamable-http", host=config.mcp.host, port=config.mcp.port)


def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"MCP server unreachable at {host}:{port}")


async def _probe_tool_channels(clients: list[LLMClient]) -> None:
    logger = get_logger("preflight")
    pending = [llm for llm in clients if llm.tool_results == "auto"]
    for llm in pending:
        llm.tool_results = "tool"

    outcomes = await asyncio.gather(*(llm.probe_tool_channel() for llm in pending), return_exceptions=True)

    broken: list[str] = []
    for llm, outcome in zip(pending, outcomes, strict=True):
        if isinstance(outcome, BaseException):
            broken.append(f"{llm.name} ('{llm.params.model}'): {outcome}")
            continue
        if outcome:
            logger.info("%s: tool results reach the model", llm.name)
            continue

        llm.tool_results = "mirror"
        try:
            mirrored = await llm.probe_tool_channel()
        except AgentError as error:
            broken.append(f"{llm.name} ('{llm.params.model}'): {error}")
            continue
        if not mirrored:
            broken.append(f"{llm.name} ('{llm.params.model}'): results never reach the model, even mirrored")
            continue
        logger.info("%s: tool results dropped by the provider, mirroring them as user messages", llm.name)

    if broken:
        raise AgentError("tool channel preflight failed:\n  " + "\n  ".join(broken))


def _build_grid(config: GridConfig, scope=None, bus: EventBus | None = None) -> Grid:
    def client(agent):
        trace = Tracer(agent.name, agent.debug)
        toolbox = Toolbox(config.mcp.url_for(agent.name), trace, agent=agent.name, bus=bus)
        return LLMClient(agent, toolbox, trace, bus=bus)

    worker = client(config.by_role("worker")[0])
    thinkers = [client(agent) for agent in config.by_role("thinker")]
    judge = client(config.by_role("judge")[0])

    grid = [worker, *thinkers, judge]
    chosen = next((llm for llm in grid if llm.name == config.summarizer), None)
    for llm in grid:
        llm.compactor = Compactor(chosen or llm, llm.trace)

    asyncio.run(_probe_tool_channels(grid))

    return Grid(worker=worker, thinkers=thinkers, judge=judge, settings=config.debate, bus=bus, scope=scope)


def _start_server(config: GridConfig) -> GridMCPServer:
    server = GridMCPServer(
        config.mcp.name,
        config.access_from_agent(),
        str(paths.workspace()),
        maxBytes=config.mcp.max_bytes,
        subprocessTimeout=config.mcp.subprocess_timeout,
        shellTimeout=config.mcp.shell_timeout,
        ignore=config.mcp.ignore,
        maxToolChars=config.mcp.max_tool_chars,
    )
    threading.Thread(target=_serve, args=(server, config), daemon=True).start()
    _wait_for_port(config.mcp.host, config.mcp.port)
    silence_third_party()
    return server


def _bootstrap() -> None:
    destination = paths.config_path()
    if destination.exists():
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(paths.TEMPLATE, destination)
    raise SystemExit(
        f"created the initial configuration at {destination}\n"
        f"write your API keys in {paths.env_path()} in the form DEEPSEEK_API_KEY=... and run again"
    )


def _parse_args() -> tuple[str, bool]:
    parser = argparse.ArgumentParser(prog="gridllm", description="A grid of LLM agents")
    parser.add_argument("--tui", action="store_true", help="run with the interactive terminal UI")
    parser.add_argument("task", nargs="*", help="task to perform")
    args = parser.parse_args()
    task = " ".join(args.task).strip()
    if not task:
        raise SystemExit("usage: gridllm [--tui] <task>")
    return task, args.tui


def _run_plain(config: GridConfig, task: str) -> None:
    server = _start_server(config)
    grid = _build_grid(config, scope=server.scope, bus=None)
    print(asyncio.run(grid.run(task)))


def _run_tui(config: GridConfig, task: str) -> None:
    try:
        from .tui import run_tui
    except ImportError as exc:
        raise SystemExit(
            "the TUI requires the optional 'gui' extra.\n"
            "install it with: uv tool install . --with gridllm[gui]\n"
            f"(missing dependency: {exc.name})"
        ) from exc
    server = _start_server(config)
    bus = EventBus()
    grid = _build_grid(config, scope=server.scope, bus=bus)
    run_tui(grid, task, bus)


def main() -> None:
    task, use_tui = _parse_args()

    _bootstrap()
    load_dotenv(paths.env_path())
    setup_logging(str(paths.log_dir()), LOG_FILE)
    config = load_config(paths.config_path())

    if use_tui:
        _run_tui(config, task)
    else:
        _run_plain(config, task)


if __name__ == "__main__":
    main()