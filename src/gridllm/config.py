import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, field_validator, model_validator

from .GridMCPServer import DEFAULT_IGNORE, DEFAULT_MAX_BYTES, DEFAULT_MAX_TOOL_CHARS


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

    @property
    def api_key(self) -> str:
        return os.environ[self.api_key_env]


class AgentConfig(BaseModel):
    role: Literal["worker", "thinker", "judge"]
    name: str
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
    confidence_threshold: float = 0.8
    verify_execution: bool = True

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
    def _summarizer_exists(self) -> "GridConfig":
        names = {agent.name for agent in self.grid}
        if self.summarizer is not None and self.summarizer not in names:
            raise ValueError(f"summarizer '{self.summarizer}' is not an agent of the grid")
        return self

    def access_from_agent(self) -> dict[str, str]:
        return {agent.name: agent.access for agent in self.grid}

    def by_role(self, role: str) -> list[AgentConfig]:
        return [agent for agent in self.grid if agent.role == role]


def load_config(path: Path) -> GridConfig:
    return GridConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
