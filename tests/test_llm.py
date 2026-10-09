import pytest
from litellm.types.utils import Choices, Message, ModelResponse

from gridllm.config import AgentConfig
from gridllm.LLMClient import AgentError, LLMClient
from gridllm.logging_setup import Tracer
from gridllm.messages import Review

AGENT = {
    "role": "judge",
    "name": "judge",
    "access": "r",
    "llm_params": {
        "model": "deepseek/deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
        "temperature": 0.0,
        "max_input_tokens": 100_000,
        "max_output_tokens": 8_192,
        "system_prompt": "you are a test",
    },
}


class NoTools:

    async def schemas(self) -> list[dict]:
        return []


@pytest.fixture
def scripted(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    calls: list[dict] = []

    def script(*answers: tuple[str | None, str]) -> LLMClient:
        pending = list(answers)

        async def fake_acompletion(**kwargs):
            calls.append(kwargs)
            content, finish = pending.pop(0)
            response = ModelResponse()
            response.choices = [Choices(message=Message(role="assistant", content=content), finish_reason=finish)]
            return response

        monkeypatch.setattr("gridllm.LLMClient.llm.acompletion", fake_acompletion)
        return LLMClient(AgentConfig.model_validate(AGENT), NoTools(), Tracer("judge", 0))

    script.calls = calls
    return script


async def test_a_conforming_answer_is_parsed(scripted):
    llm = scripted(('{"approved": true, "note": "fine"}', "stop"))
    assert (await llm.ask("review", Review)).approved is True


async def test_a_malformed_answer_is_repaired_once(scripted):
    llm = scripted(("approved, all fine", "stop"), ('{"approved": true, "note": "fine"}', "stop"))
    assert (await llm.ask("review", Review)).note == "fine"
    assert len(scripted.calls) == 2


@pytest.mark.parametrize("content", [None, "", "   "])
async def test_an_empty_answer_fails_instead_of_being_repaired(scripted, content):
    llm = scripted((content, "stop"))
    with pytest.raises(AgentError, match="empty answer"):
        await llm.ask("review", Review)
    assert len(scripted.calls) == 1


async def test_a_truncated_answer_fails_instead_of_being_repaired(scripted):
    llm = scripted(('{"approved": true, "no', "length"))
    with pytest.raises(AgentError, match="truncated"):
        await llm.ask("review", Review)
    assert len(scripted.calls) == 1


async def test_transient_provider_errors_are_retried(scripted):
    llm = scripted(("plain answer", "stop"))
    assert await llm.ask("say something") == "plain answer"
    assert scripted.calls[0]["num_retries"] > 0
