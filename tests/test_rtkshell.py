import pytest

from gridllm.GridMCPServer.rtkshell import rewriteCommand


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("ls -la", "rtk ls -la"),
        ("grep -n foo *.c | wc -l", "rtk grep -n foo *.c | rtk wc -l"),
        ("cd src && ls", "cd src && rtk ls"),
        ("find . -name '*.c'", "rtk find . -name '*.c'"),
        ("make 2>&1 | grep error", "make 2>&1 | rtk grep error"),
    ],
)
def test_known_commands_are_proxied(command, expected):
    assert rewriteCommand(command) == expected


@pytest.mark.parametrize(
    "command",
    [
        "echo 'ls'",
        "make all",
        "ls > out.txt",
        "./configure",
        "VAR=1 grep x",
    ],
)
def test_these_commands_are_left_alone(command):
    assert rewriteCommand(command) == command


def test_an_unbalanced_quote_is_left_alone():
    assert rewriteCommand("grep 'unterminated") == "grep 'unterminated"
