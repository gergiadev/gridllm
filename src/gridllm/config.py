import os
from pathlib import Path
from typing import Literal

import litellm
import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from .GridMCPServer import DEFAULT_IGNORE, DEFAULT_MAX_BYTES, DEFAULT_MAX_TOOL_CHARS

ACCESS_BY_ROLE = {"worker": "rw", "thinker": "r", "judge": "r"}


def _model_limits(model: str) -> tuple[int | None, int | None]:
    try:
        info = litellm.get_model_info(model)
    except Exception:  # noqa: BLE001
        return None, None
    return info.get("max_input_tokens"), info.get("max_output_tokens")


class LLMParams(BaseModel):
    model: str
    api_key_env: str
    temperature: float
    max_input_tokens: int
    max_output_tokens: int
    system_prompt: str
    api_base: str | None = None
    max_tool_rounds: int = 25
    tool_results: Literal["auto", "tool", "mirror"] = "auto"

    @field_validator("max_tool_rounds")
    @classmethod
    def _is_positive(cls, rounds: int) -> int:
        if rounds < 1:
            raise ValueError("max_tool_rounds must be at least 1")
        return rounds

    @field_validator("api_key_env")
    @classmethod
    def _is_set(cls, name: str) -> str:
        if not os.getenv(name):
            raise ValueError(f"environment variable {name} is not set")
        return name

    @model_validator(mode="after")
    def _budget_fits_the_model(self) -> "LLMParams":
        window, output = _model_limits(self.model)
        if output is not None and self.max_output_tokens > output:
            raise ValueError(
                f"{self.model}: max_output_tokens {self.max_output_tokens} exceeds the "
                f"{output} the model can emit"
            )
        if window is not None and self.max_input_tokens + self.max_output_tokens > window:
            raise ValueError(
                f"{self.model}: max_input_tokens {self.max_input_tokens} plus max_output_tokens "
                f"{self.max_output_tokens} exceeds the {window} token context window, so no "
                "request can ever be served"
            )
        return self

    @property
    def api_key(self) -> str:
        return os.environ[self.api_key_env]


class AgentConfig(BaseModel):
    role: Literal["worker", "thinker", "judge"]
    name: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    access: Literal["r", "rw"]
    llm_params: LLMParams
    debug: Literal[0, 1, 2, 3] = 0


class MCPConfig(BaseModel):
    name: str
    host: str
    port: int
    path: str
    max_bytes: int = DEFAULT_MAX_BYTES
    subprocess_timeout: int = 30
    shell_timeout: int = 60
    max_tool_chars: int = DEFAULT_MAX_TOOL_CHARS
    ignore: list[str] = list(DEFAULT_IGNORE)

    def url_for(self, agent: str) -> str:
        return f"http://{self.host}:{self.port}{self.path}?agent={agent}"


class DebateConfig(BaseModel):
    max_exchanges: int = 5
    min_exchanges: int = 2
    confidence_threshold: float = Field(default=0.8, ge=0, le=1)
    verify_execution: bool = Field(
        default=True,
        description=(
            "Ask the judge to re-read the changed files and report whether the verdict was "
            "applied. The outcome is reported, not enforced: a rejected review is surfaced as "
            "an error and appended to the result, but the run still ends and nothing is undone."
        ),
    )

    @model_validator(mode="after")
    def _exchanges_are_consistent(self) -> "DebateConfig":
        if self.min_exchanges < 1:
            raise ValueError("min_exchanges must be at least 1")
        if self.min_exchanges > self.max_exchanges:
            raise ValueError("min_exchanges cannot exceed max_exchanges")
        return self


class GridConfig(BaseModel):
    grid: list[AgentConfig]
    mcp: MCPConfig
    debate: DebateConfig = DebateConfig()
    summarizer: str | None = None

    @model_validator(mode="after")
    def _roles_are_complete(self) -> "GridConfig":
        for role in ("worker", "judge"):
            found = len(self.by_role(role))
            if found != 1:
                raise ValueError(f"the grid needs exactly one {role}, found {found}")
        thinkers = len(self.by_role("thinker"))
        if thinkers < 2:
            raise ValueError(
                f"the grid needs at least two thinkers, found {thinkers}: with nobody to oppose it "
                "a proposal can never close the debate, so every run would burn max_exchanges"
            )
        return self

    @model_validator(mode="after")
    def _agents_are_coherent(self) -> "GridConfig":
        names = [agent.name for agent in self.grid]
        repeated = sorted({name for name in names if names.count(name) > 1})
        if repeated:
            raise ValueError(f"agent names must be unique, repeated: {', '.join(repeated)}")
        for agent in self.grid:
            expected = ACCESS_BY_ROLE[agent.role]
            if agent.access != expected:
                raise ValueError(
                    f"{agent.name}: a {agent.role} needs access '{expected}', found '{agent.access}'"
                )
        return self

    @model_validator(mode="after")
    def _summarizer_exists(self) -> "GridConfig":
        names = {agent.name for agent in self.grid}
        if self.summarizer is not None and self.summarizer not in names:
            raise ValueError(f"summarizer '{self.summarizer}' is not an agent of the grid")
        return self

    def access_from_agent(self) -> dict[str, str]:
        return {agent.name: agent.access for agent in self.grid}

    def secret_env(self) -> set[str]:
        return {agent.llm_params.api_key_env for agent in self.grid}

    def by_role(self, role: str) -> list[AgentConfig]:
        return [agent for agent in self.grid if agent.role == role]


def load_config(path: Path) -> GridConfig:
    return GridConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
