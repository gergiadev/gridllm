import asyncio
from pathlib import Path

import pytest
from litellm.types.utils import (
    ChatCompletionMessageToolCall,
    Choices,
    Function,
    Message,
    ModelResponse,
)

from gridllm import gridllm
from gridllm.config import load_config

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "src" / "gridllm" / "config.default.yml"


@pytest.fixture(autouse=True)
def api_keys(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    monkeypatch.setenv("OLLAMA_API_KEY", "test")


def _reply(message: Message) -> ModelResponse:
    response = ModelResponse()
    response.choices = [Choices(message=message)]
    return response


@pytest.fixture
def recorded_loops(monkeypatch) -> list:
    seen: list = []

    async def fake_acompletion(**kwargs):
        seen.append(asyncio.get_running_loop())
        if kwargs.get("tools"):
            call = ChatCompletionMessageToolCall(
                id="probe-1",
                function=Function(name="grid_probe", arguments="{}"),
                type="function",
            )
            return _reply(Message(role="assistant", content=None, tool_calls=[call]))
        echoed = next(
            (m.get("content") or "" for m in reversed(kwargs["messages"]) if m.get("role") == "tool"),
            "",
        )
        return _reply(Message(role="assistant", content=echoed))

    monkeypatch.setattr(gridllm, "acompletion", fake_acompletion, raising=False)
    monkeypatch.setattr("gridllm.LLMClient.llm.acompletion", fake_acompletion)
    return seen


def test_build_grid_is_a_coroutine():
    assert asyncio.iscoroutinefunction(gridllm._build_grid)


def test_preflight_runs_in_the_caller_loop(recorded_loops):
    config = load_config(DEFAULT_CONFIG)
    caller: list = []

    async def scenario():
        grid = await gridllm._build_grid(config, scope=None, bus=None)
        caller.append(asyncio.get_running_loop())
        return grid

    asyncio.run(scenario())

    assert recorded_loops, "the preflight never reached the model"
    assert caller
    assert {id(loop) for loop in recorded_loops} == {id(caller[0])}


def test_every_agent_is_probed_and_keeps_the_tool_channel(recorded_loops):
    config = load_config(DEFAULT_CONFIG)
    grid = asyncio.run(gridllm._build_grid(config, scope=None, bus=None))
    clients = [grid.worker, grid.judge, *grid.thinkers]
    assert len(clients) == len(config.grid)
    assert all(client.tool_results == "tool" for client in clients)
