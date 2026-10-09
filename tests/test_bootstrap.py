import socket

import pytest

from gridllm import gridllm, paths


@pytest.fixture
def fresh_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("GRIDLLM_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_first_run_without_arguments_creates_the_config(fresh_home, monkeypatch):
    monkeypatch.setattr("sys.argv", ["gridllm"])
    destination = paths.config_path()
    assert not destination.exists()

    with pytest.raises(SystemExit) as exit_info:
        gridllm.main()

    assert "created the initial configuration" in str(exit_info.value)
    assert destination.exists()
    assert destination.read_text(encoding="utf-8") == paths.TEMPLATE.read_text(encoding="utf-8")


def test_first_run_points_at_the_env_file(fresh_home, monkeypatch):
    monkeypatch.setattr("sys.argv", ["gridllm"])
    with pytest.raises(SystemExit) as exit_info:
        gridllm.main()
    assert str(paths.env_path()) in str(exit_info.value)


def test_a_missing_task_still_reports_the_usage_once_configured(fresh_home, monkeypatch):
    paths.config_path().parent.mkdir(parents=True, exist_ok=True)
    paths.config_path().write_text(paths.TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["gridllm"])

    with pytest.raises(SystemExit) as exit_info:
        gridllm.main()

    assert "usage: gridllm" in str(exit_info.value)


def test_bootstrap_leaves_an_existing_config_untouched(fresh_home):
    destination = paths.config_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("mine\n", encoding="utf-8")
    gridllm._bootstrap()
    assert destination.read_text(encoding="utf-8") == "mine\n"


def test_a_taken_port_stops_the_startup():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        with pytest.raises(SystemExit, match="cannot start the MCP server"):
            gridllm._ensure_port_free("127.0.0.1", taken.getsockname()[1])
