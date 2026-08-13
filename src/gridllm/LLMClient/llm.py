import json
import logging
import secrets

from litellm import acompletion, token_counter
from pydantic import BaseModel

from .. import structured
from ..config import AgentConfig
from ..events import (
    KIND_LLM_CALL,
    KIND_LLM_RESPONSE,
    KIND_LLM_THINKING,
    KIND_TOKEN_USAGE,
    EventBus,
)
from ..logging_setup import Tracer, traced
from .toolbox import Toolbox

FORCE_FINAL_MARGIN = 3

MAX_ARGUMENT_CHARS = 120

FORCE_FINAL_SYSTEM = (
    "Stop calling tools. You have gathered enough information.\n"
    "Reply ONLY with the requested JSON object, no surrounding text and no code fences."
)

MIRROR_HEADER = "Results of the tools just executed:"

PROBE_TOOL_NAME = "grid_probe"

PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": PROBE_TOOL_NAME,
        "description": "Return the probe token. Takes no arguments.",
        "parameters": {"type": "object", "properties": {}},
    },
}

PROBE_SYSTEM = (
    f"You are running a connectivity check. Call the tool {PROBE_TOOL_NAME} once, "
    "then reply with the exact token it returned and nothing else."
)

PROBE_USER = f"Call {PROBE_TOOL_NAME} and report the token it returns."

logging.getLogger("litellm").setLevel(logging.CRITICAL)
logging.getLogger("litellm.litellm").setLevel(logging.CRITICAL)
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)
logging.getLogger("LiteLLM Router").setLevel(logging.CRITICAL)
logging.getLogger("LiteLLM Proxy").setLevel(logging.CRITICAL)


class AgentError(RuntimeError):
    pass


def _emit_usage(bus: EventBus | None, agent: str, response) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    EventBus.emit_to(
        bus,
        KIND_TOKEN_USAGE,
        {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        },
        agent,
    )


class LLMClient:

    def __init__(
        self,
        agent: AgentConfig,
        toolbox: Toolbox,
        trace: Tracer,
        bus: EventBus | None = None,
    ):
        self.name = agent.name
        self.params = agent.llm_params
        self.toolbox = toolbox
        self.trace = trace
        self.bus = bus
        self.compactor = None
        self.tool_results = agent.llm_params.tool_results

    @traced
    async def ask(self, prompt: str, schema: type[BaseModel] | None = None):
        try:
            return await self._ask(prompt, schema)
        except AgentError:
            raise
        except Exception as error:
            raise AgentError(f"{self.name}: {error}") from error

    async def _ask(self, prompt: str, schema: type[BaseModel] | None):
        self.trace.prompt(prompt)
        EventBus.emit_to(self.bus, KIND_LLM_CALL, {"prompt": prompt, "schema": schema.__name__ if schema else None}, self.name)

        tools = await self.toolbox.schemas()
        messages = [
            {"role": "system", "content": self.params.system_prompt},
            {"role": "user", "content": structured.request(prompt, schema)},
        ]

        max_rounds = self.params.max_tool_rounds
        force_final_at = max(1, max_rounds - FORCE_FINAL_MARGIN)

        for round_index in range(max_rounds):
            messages = await self._compact(messages, tools)
            self._check_context(messages, tools)

            active_tools = tools
            if round_index >= force_final_at:
                active_tools = None
                messages = self._inject_force_final(messages)

            message = await self._complete(messages, active_tools)
            self._trace_thinking(message)

            if not message.tool_calls:
                return await self._finalize(message.content, schema)

            messages.append(message.model_dump())
            results = [await self._tool_result(call) for call in message.tool_calls]
            messages.extend(results)
            if self.tool_results == "mirror":
                messages.append(_mirror_message(results))

        self.trace.prompt(f"exhausted {max_rounds} tool rounds, asking for a final answer with no tools")
        message = await self._complete(self._inject_force_final(messages), None)
        self._trace_thinking(message)
        if message.tool_calls or not message.content:
            raise AgentError(f"{self.name}: exceeded {max_rounds} tool rounds without an answer")
        return await self._finalize(message.content, schema)

    def _trace_thinking(self, message) -> None:
        thinking = getattr(message, "reasoning_content", None)
        self.trace.thinking(thinking)
        if thinking:
            EventBus.emit_to(self.bus, KIND_LLM_THINKING, {"thinking": thinking}, self.name)

    async def _finalize(self, content: str, schema: type[BaseModel] | None):
        result = await self._parse(content, schema)
        EventBus.emit_to(self.bus, KIND_LLM_RESPONSE, {"content": content, "result": _safe_dump(result)}, self.name)
        return result

    @staticmethod
    def _inject_force_final(messages: list[dict]) -> list[dict]:
        last = messages[-1] if messages else {}
        if last.get("role") == "user" and FORCE_FINAL_SYSTEM in (last.get("content") or ""):
            return messages
        return messages + [{"role": "user", "content": FORCE_FINAL_SYSTEM}]

    @traced
    async def _complete(self, messages: list[dict], tools: list[dict] | None):
        response = await acompletion(
            model=self.params.model,
            api_base=self.params.api_base,
            api_key=self.params.api_key,
            temperature=self.params.temperature,
            max_tokens=self.params.max_output_tokens,
            messages=messages,
            tools=tools or None,
        )
        _emit_usage(self.bus, self.name, response)
        return response.choices[0].message

    @traced
    async def _parse(self, content: str, schema: type[BaseModel] | None):
        if schema is None:
            return content

        try:
            return structured.convert(content, schema)
        except ValueError as error:
            self.trace.prompt(f"non-conforming response, retrying: {error}")

        try:
            repaired = await self.plain(
                structured.REPAIR_SYSTEM,
                structured.repair(content, schema),
                self.params.max_output_tokens,
            )
            return structured.convert(repaired, schema)
        except ValueError as error:
            raise AgentError(f"{self.name}: failed to parse response after repair: {error}") from error

    @traced
    async def plain(self, system: str, prompt: str, max_tokens: int) -> str:
        self.trace.prompt(prompt)
        EventBus.emit_to(self.bus, KIND_LLM_CALL, {"prompt": prompt, "schema": None}, self.name)
        response = await acompletion(
            model=self.params.model,
            api_base=self.params.api_base,
            api_key=self.params.api_key,
            temperature=self.params.temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        _emit_usage(self.bus, self.name, response)
        content = response.choices[0].message.content
        EventBus.emit_to(self.bus, KIND_LLM_RESPONSE, {"content": content, "result": None}, self.name)
        return content

    @traced
    async def _compact(self, messages: list[dict], tools: list[dict]) -> list[dict]:
        if self.compactor is None:
            return messages
        return await self.compactor.fit(messages, tools, self.params.model, self.params.max_input_tokens)

    @traced
    def _check_context(self, messages: list[dict], tools: list[dict]) -> None:
        used = token_counter(model=self.params.model, messages=messages, tools=tools)
        if used > self.params.max_input_tokens:
            raise AgentError(
                f"{self.name}: context of {used} tokens still exceeds the limit of "
                f"{self.params.max_input_tokens} after compaction"
            )

    @traced
    async def probe_tool_channel(self) -> bool:
        try:
            return await self._probe()
        except AgentError:
            raise
        except Exception as error:
            raise AgentError(f"{self.name}: {error}") from error

    async def _probe(self) -> bool:
        nonce = secrets.token_hex(8)
        messages = [
            {"role": "system", "content": PROBE_SYSTEM},
            {"role": "user", "content": PROBE_USER},
        ]

        message = await self._complete(messages, [PROBE_TOOL])
        if not message.tool_calls:
            self.trace.prompt(f"tool channel probe: {self.name} did not call {PROBE_TOOL_NAME}")
            return False

        messages.append(message.model_dump())
        for call in message.tool_calls:
            messages.append(_tool_message(call, PROBE_TOOL_NAME, nonce))
        if self.tool_results == "mirror":
            messages.append(_mirror_message(messages[-len(message.tool_calls):]))

        reply = await self._complete(messages, [PROBE_TOOL])
        seen = nonce in (reply.content or "")
        self.trace.prompt(f"tool channel probe: {self.name} {'sees' if seen else 'does not see'} tool results")
        return seen

    @traced
    async def _tool_result(self, call) -> dict:
        name = call.function.name
        try:
            arguments = _arguments_of(call)
        except (TypeError, ValueError) as error:
            self.trace.result(name, str(error), error=True)
            return _tool_message(call, name, f"Tool execution error: {error}")
        content = await self.toolbox.call(name, arguments)
        return _tool_message(call, name, _label(name, arguments, content))


def _arguments_of(call) -> dict:
    raw = call.function.arguments
    if isinstance(raw, dict):
        return raw
    if not raw or not str(raw).strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"arguments are not valid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise TypeError(f"arguments must be a JSON object, got {type(parsed).__name__}")
    return parsed


def _label(name: str, arguments: dict, content: str) -> str:
    shown = ", ".join(f"{key}={_short(value)}" for key, value in arguments.items())
    return f"{name}({shown}) ->\n{content}"


def _short(value) -> str:
    text = repr(value)
    return text if len(text) <= MAX_ARGUMENT_CHARS else f"{text[:MAX_ARGUMENT_CHARS]}..."


def _tool_message(call, name: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": call.id, "name": name, "content": content}


def _mirror_message(results: list[dict]) -> dict:
    body = "\n\n".join(str(result.get("content") or "") for result in results)
    return {"role": "user", "content": f"{MIRROR_HEADER}\n{body}"}


def _safe_dump(value) -> str:
    if isinstance(value, BaseModel):
        return value.model_dump_json(indent=2)
    if isinstance(value, str):
        return value[:2000]
    return str(value)[:2000]