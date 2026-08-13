import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

KIND_LLM_CALL = "llm.call"
KIND_LLM_RESPONSE = "llm.response"
KIND_LLM_THINKING = "llm.thinking"
KIND_TOOL_CALL = "tool.call"
KIND_TOOL_RESULT = "tool.result"
KIND_DEBATE_ROUND = "debate.round"
KIND_DEBATE_DONE = "debate.done"
KIND_ESCALATION = "escalation"
KIND_VERDICT = "verdict"
KIND_REVIEW = "review"
KIND_EXECUTION_START = "execution.start"
KIND_EXECUTION_DONE = "execution.done"
KIND_RUN_DONE = "run.done"
KIND_LOG = "log"
KIND_FINDING = "finding"
KIND_ERROR = "error"
KIND_TOKEN_USAGE = "token.usage"


@dataclass
class Event:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    agent: str | None = None
    ts: float = field(default_factory=time.time)


class EventBus:
    _history: list[Event]
    _subscribers: list[asyncio.Queue[Event]]

    def __init__(self) -> None:
        self._history = []
        self._subscribers = []

    def emit(self, event: Event) -> None:
        self._history.append(event)
        for queue in self._subscribers:
            queue.put_nowait(event)

    def subscribe(self) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        for event in self._history:
            queue.put_nowait(event)
        self._subscribers.append(queue)
        return self._drain(queue)

    async def _drain(self, queue: asyncio.Queue[Event]) -> AsyncIterator[Event]:
        try:
            while True:
                yield await queue.get()
        finally:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    @staticmethod
    def emit_to(bus: "EventBus | None", kind: str, payload: dict[str, Any] | None = None, agent: str | None = None) -> None:
        if bus is None:
            return
        bus.emit(Event(kind=kind, payload=payload or {}, agent=agent))