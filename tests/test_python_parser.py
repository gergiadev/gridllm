from gridllm.GridMCPServer.languages.python_parser import PythonParser

SOURCE = """\
import functools

LIMIT = 10


class Cache:
    size = 1

    @functools.cache
    def get(self):
        return LIMIT


async def fetch():
    return 1
"""


def test_kinds_follow_the_enclosing_scope():
    kinds = {s["name"]: s["kind"] for s in PythonParser().listSymbols(SOURCE)}
    assert kinds == {
        "LIMIT": "variable",
        "Cache": "class",
        "size": "attribute",
        "get": "method",
        "fetch": "async function",
    }


def test_a_decorated_body_starts_at_its_decorator():
    body = PythonParser().getSymbolBody(SOURCE, "get")[0]
    assert body["line"] == 9
    assert body["body"].splitlines()[0].strip() == "@functools.cache"


def test_a_variable_body_can_be_extracted():
    assert [entry["body"] for entry in PythonParser().getSymbolBody(SOURCE, "LIMIT")] == ["LIMIT = 10"]
