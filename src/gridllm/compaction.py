from litellm import token_counter

from .LLMClient.llm import MIRROR_HEADER
from .logging_setup import Tracer, traced

THRESHOLD = 0.8
MAX_SUMMARY_TOKENS = 2000
MAX_BLOCK_CHARS = 4000
MAX_TOOL_CHARS = 8000
MAX_SUMMARY_INPUT_CHARS = 200_000

SYSTEM_PROMPT = """Summarize the operations already carried out in a conversation between an agent and its tools.
Keep: files read, relevant contents, results obtained, errors encountered.
Drop: repetitions and text not needed to carry the work forward.
Reply with the summary only, in compact form."""


def _carries_tool_output(message: dict) -> bool:
    if message.get("role") == "tool":
        return True
    content = message.get("content")
    return isinstance(content, str) and content.startswith(MIRROR_HEADER)


def _describe(message: dict) -> str:
    calls = "".join(
        f" {call['function']['name']}({call['function']['arguments']})"
        for call in message.get("tool_calls") or []
    )
    return f"[{message.get('role')}]{calls} {str(message.get('content') or '')[:MAX_BLOCK_CHARS]}"


class Compactor:

    def __init__(self, summarizer, trace: Tracer):
        self.summarizer = summarizer
        self.trace = trace

    @traced
    async def fit(self, messages: list[dict], tools: list[dict], model: str, budget: int) -> list[dict]:
        if self._fits(messages, tools, model, budget):
            return messages

        clipped = self._clip_tools(messages)
        if clipped is not messages:
            self.trace.prompt("compaction: tool results truncated")
            messages = clipped
            if self._fits(messages, tools, model, budget):
                return messages

        head, groups = self._partition(messages)
        if len(groups) >= 2:
            summary = await self._summarize(groups[:-1])
            messages = head + [{"role": "user", "content": summary}] + groups[-1]

        return messages

    @staticmethod
    def _fits(messages: list[dict], tools: list[dict], model: str, budget: int) -> bool:
        return token_counter(model=model, messages=messages, tools=tools) <= budget * THRESHOLD

    @staticmethod
    def _clip_tools(messages: list[dict]) -> list[dict]:
        clipped = []
        changed = False

        for message in messages:
            content = message.get("content") or ""
            if not _carries_tool_output(message) or not isinstance(content, str) or len(content) <= MAX_TOOL_CHARS:
                clipped.append(message)
                continue
            dropped = len(content) - MAX_TOOL_CHARS
            clipped.append({**message, "content": f"{content[:MAX_TOOL_CHARS]}\n[{dropped} characters truncated]"})
            changed = True

        return clipped if changed else messages

    @staticmethod
    def _partition(messages: list[dict]) -> tuple[list[dict], list[list[dict]]]:
        head: list[dict] = []
        groups: list[list[dict]] = []

        for message in messages:
            if message.get("role") == "assistant":
                groups.append([message])
            elif groups:
                groups[-1].append(message)
            else:
                head.append(message)

        return head, groups

    @traced
    async def _summarize(self, groups: list[list[dict]]) -> str:
        text = "\n".join(_describe(message) for group in groups for message in group)
        summary = await self.summarizer.plain(SYSTEM_PROMPT, text[-MAX_SUMMARY_INPUT_CHARS:], MAX_SUMMARY_TOKENS)
        return f"Summary of previous operations:\n{summary}"
