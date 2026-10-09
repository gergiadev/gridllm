import json

from gridllm.compaction import Compactor
from gridllm.logging_setup import Tracer

MODEL = "deepseek/deepseek-chat"


class Summarizer:

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def plain(self, system: str, prompt: str, max_tokens: int) -> str:
        self.prompts.append(prompt)
        return "read vm.c, found the bound check"


def _round(index: int, path: str, output: str) -> list[dict]:
    call = {
        "id": f"call-{index}",
        "type": "function",
        "function": {"name": "read_file", "arguments": json.dumps({"path": path})},
    }
    return [
        {"role": "assistant", "content": None, "tool_calls": [call]},
        {"role": "tool", "tool_call_id": call["id"], "name": "read_file", "content": output},
    ]


def _conversation() -> list[dict]:
    return [
        {"role": "system", "content": "you are a test"},
        {"role": "user", "content": "find the bug"},
        *_round(0, "vm.c", "int stack[8];"),
        *_round(1, "chunk.c", "void emit(void);"),
    ]


async def test_a_conversation_within_budget_is_left_alone():
    summarizer = Summarizer()
    messages = _conversation()
    assert await Compactor(summarizer, Tracer("t", 0)).fit(messages, [], MODEL, 100_000) is messages
    assert summarizer.prompts == []


async def test_older_rounds_are_summarised_and_the_last_one_is_kept():
    summarizer = Summarizer()
    messages = _conversation()
    fitted = await Compactor(summarizer, Tracer("t", 0)).fit(messages, [], MODEL, 10)
    assert fitted[:2] == messages[:2]
    assert fitted[2]["content"].startswith("Summary of previous operations:")
    assert fitted[3:] == messages[-2:]


async def test_the_summary_request_names_the_tool_calls():
    summarizer = Summarizer()
    await Compactor(summarizer, Tracer("t", 0)).fit(_conversation(), [], MODEL, 10)
    assert "read_file" in summarizer.prompts[0]
    assert "vm.c" in summarizer.prompts[0]
    assert "chunk.c" not in summarizer.prompts[0]
