from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from gridllm.config import DebateConfig, GridConfig, LLMParams, load_config

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "src" / "gridllm" / "config.default.yml"

KNOWN = "deepseek/deepseek-chat"

UNKNOWN = "openai/some-locally-served-model"


@pytest.fixture(autouse=True)
def api_keys(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    monkeypatch.setenv("OLLAMA_API_KEY", "test")


def params(**overrides) -> LLMParams:
    base = {
        "model": KNOWN,
        "api_key_env": "DEEPSEEK_API_KEY",
        "temperature": 0.0,
        "max_input_tokens": 100_000,
        "max_output_tokens": 8_192,
        "system_prompt": "you are a test",
    }
    return LLMParams(**{**base, **overrides})


def test_a_budget_inside_the_window_is_accepted():
    assert params().max_input_tokens == 100_000


def test_output_beyond_what_the_model_emits_is_refused():
    with pytest.raises(ValidationError, match="exceeds the 8192 the model can emit"):
        params(max_output_tokens=99_999)


def test_input_plus_output_beyond_the_window_is_refused():
    with pytest.raises(ValidationError, match="no request can ever be served"):
        params(max_input_tokens=131_072, max_output_tokens=8_192)


def test_a_budget_exactly_filling_the_window_is_accepted():
    assert params(max_input_tokens=131_072 - 8_192, max_output_tokens=8_192)


def test_an_unknown_model_is_left_alone():
    assert params(model=UNKNOWN, max_input_tokens=131_072, max_output_tokens=131_072)


def test_a_missing_api_key_is_refused(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    with pytest.raises(ValidationError, match="is not set"):
        params()


def test_the_shipped_default_config_validates():
    config = load_config(DEFAULT_CONFIG)
    assert [agent.role for agent in config.grid].count("worker") == 1
    assert [agent.role for agent in config.grid].count("judge") == 1
    assert len(config.by_role("thinker")) >= 2


def test_the_url_carries_the_agent_name():
    config = load_config(DEFAULT_CONFIG)
    assert config.mcp.url_for("worker").endswith("?agent=worker")


def _grid_with(**changes) -> dict:
    raw = yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    raw["grid"][1].update(changes)
    return raw


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"name": "worker"}, "agent names must be unique"),
        ({"name": "thinker 1"}, "String should match pattern"),
        ({"access": "rw"}, "a thinker needs access 'r'"),
    ],
)
def test_an_incoherent_grid_is_refused(changes, message):
    with pytest.raises(ValidationError, match=message):
        GridConfig.model_validate(_grid_with(**changes))


def test_a_threshold_outside_the_unit_interval_is_refused():
    with pytest.raises(ValidationError):
        DebateConfig(confidence_threshold=80)


def test_the_api_key_variables_are_the_secret_environment():
    assert load_config(DEFAULT_CONFIG).secret_env() == {"OLLAMA_API_KEY", "DEEPSEEK_API_KEY"}
