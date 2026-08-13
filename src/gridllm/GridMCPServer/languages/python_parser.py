import ast

from .base import SourceParser
from .parser_factory import register_parser

_DEFINITIONS = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _signature(node: ast.AST, sourceLines: list[str]) -> str:
    line = getattr(node, "lineno", 0)
    if line <= 0 or line > len(sourceLines):
        return ""
    return sourceLines[line - 1].strip()


def _docstring(node: ast.AST) -> str | None:
    if isinstance(node, ast.Assign):
        return None
    return ast.get_docstring(node)


def _kindOf(node: ast.AST, inClass: bool) -> str:
    if isinstance(node, ast.ClassDef):
        return "class"
    if isinstance(node, ast.AsyncFunctionDef):
        return "async method" if inClass else "async function"
    if isinstance(node, ast.FunctionDef):
        return "method" if inClass else "function"
    if isinstance(node, ast.Assign):
        return "variable"
    return "other"


def _toEntry(node: ast.AST, sourceLines: list[str], inClass: bool) -> dict | None:
    if isinstance(node, _DEFINITIONS):
        name = node.name
    elif isinstance(node, ast.Assign):
        targets = [t for t in node.targets if isinstance(t, ast.Name)]
        if not targets:
            return None
        name = ", ".join(t.id for t in targets)
    else:
        return None
    return {
        "kind": _kindOf(node, inClass),
        "name": name,
        "line": node.lineno,
        "endLine": getattr(node, "end_lineno", node.lineno),
        "signature": _signature(node, sourceLines),
        "docstring": _docstring(node),
    }


def _walk(node: ast.AST, sourceLines: list[str], inClass: bool, acc: list[dict]) -> None:
    if isinstance(node, (*_DEFINITIONS, ast.Assign)):
        entry = _toEntry(node, sourceLines, inClass)
        if entry is not None:
            acc.append(entry)
    newInClass = inClass or isinstance(node, ast.ClassDef)
    for child in ast.iter_child_nodes(node):
        _walk(child, sourceLines, newInClass, acc)


def _bodyEntry(node: ast.AST, sourceLines: list[str]) -> dict:
    start = node.lineno
    end = getattr(node, "end_lineno", start)
    body = "\n".join(sourceLines[start - 1:end])
    kind = "class"
    if isinstance(node, ast.AsyncFunctionDef):
        kind = "async function"
    elif isinstance(node, ast.FunctionDef):
        kind = "function"
    return {
        "kind": kind,
        "name": node.name,
        "line": start,
        "endLine": end,
        "body": body,
    }


@register_parser(".py")
class PythonParser(SourceParser):

    def listSymbols(self, sourceText: str) -> list[dict]:
        tree = ast.parse(sourceText)
        sourceLines = sourceText.splitlines()
        acc: list[dict] = []
        _walk(tree, sourceLines, False, acc)
        return acc

    def getSymbolBody(self, sourceText: str, symbolName: str) -> list[dict]:
        lines = sourceText.splitlines()
        tree = ast.parse(sourceText)
        return [
            _bodyEntry(node, lines)
            for node in ast.walk(tree)
            if isinstance(node, _DEFINITIONS) and node.name == symbolName
        ]