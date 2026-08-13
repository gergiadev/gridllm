import functools
import inspect
import logging
from pathlib import Path

NAMES = 1
PROMPTS = 2
THINKING = 3

MAX_TRACE_CHARS = 500

ROOT = "gridllm"
LOG_FORMAT = "%(asctime)s [%(name)s] %(message)s"

NOISY = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "uvicorn.asgi",
    "litellm",
    "litellm.litellm",
    "LiteLLM",
    "mcp",
    "mcp.server",
    "httpx",
    "httpx2",
    "httpcore",
    "anyio",
    "starlette",
    "sse_starlette",
    "asyncio",
)


def silence_third_party() -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.CRITICAL)

    for name in NOISY:
        noisy = logging.getLogger(name)
        noisy.handlers.clear()
        noisy.setLevel(logging.CRITICAL)
        noisy.propagate = False


def setup_logging(logpath: str, filename: str) -> None:
    path = Path(logpath) / filename
    path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))

    logger = logging.getLogger(ROOT)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    silence_third_party()


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT}.{name}")


class Tracer:

    def __init__(self, owner: str, level: int):
        self.logger = get_logger(owner)
        self.level = level

    def entered(self, name: str) -> None:
        if self.level >= NAMES:
            self.logger.info("call: %s", name)

    def tool(self, name: str, arguments) -> None:
        if self.level >= NAMES:
            self.logger.info("tool -> %s %s", name, str(arguments)[:MAX_TRACE_CHARS])

    def result(self, name: str, content: str, error: bool = False) -> None:
        if self.level >= NAMES:
            self.logger.info(
                "tool <- %s%s [%d chars] %s",
                name,
                " FAILED" if error else "",
                len(content),
                content[:MAX_TRACE_CHARS].replace("\n", "\\n"),
            )

    def prompt(self, text: str) -> None:
        if self.level >= PROMPTS:
            self.logger.info("prompt: %s", text)

    def thinking(self, text: str | None) -> None:
        if text and self.level >= THINKING:
            self.logger.info("thinking: %s", text)


def traced(fn):
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def wrapper(self, *args, **kwargs):
            self.trace.entered(fn.__qualname__)
            return await fn(self, *args, **kwargs)
    else:
        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            self.trace.entered(fn.__qualname__)
            return fn(self, *args, **kwargs)
    return wrapper
