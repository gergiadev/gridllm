import os
import time
from pathlib import Path

APP = "gridllm"
CONFIG_ENV = "GRIDLLM_CONFIG"
TEMPLATE = Path(__file__).parent / "config.default.yml"


def _base(variable: str, default: str) -> Path:
    root = os.getenv(variable)
    return (Path(root) if root else Path.home() / default) / APP


def config_dir() -> Path:
    return _base("XDG_CONFIG_HOME", ".config")


def config_path() -> Path:
    choice = os.getenv(CONFIG_ENV)
    return Path(choice).expanduser() if choice else config_dir() / "config.yml"


def env_path() -> Path:
    return config_dir() / ".env"


def local_dir() -> Path:
    path = Path.cwd() / f".{APP}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = local_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_dir() -> Path:
    path = local_dir() / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_path() -> Path:
    return run_dir() / f"{time.strftime('%Y%m%d-%H%M%S')}.json"


def workspace() -> Path:
    return Path.cwd()