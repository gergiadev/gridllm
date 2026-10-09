import ast

from .base import SourceParser
from .parser_factory import register_parser

_DEFINITIONS = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)

_ASSIGNMENTS = (ast.Assign, ast.AnnAssign)


def _signature(node: ast.AST, sourceLines: list[str]) -> str:
    line = getattr(node, "lineno", 0)
    if line <= 0 or line > len(sourceLines):
        return ""
    return sourceLines[line - 1].strip()


def _docstring(node: ast.AST) -> str | None:
    if isinstance(node, _ASSIGNMENTS):
        return None
    return ast.get_docstring(node)


def _kindOf(node: ast.AST, inClass: bool) -> str:
    if isinstance(node, ast.ClassDef):
        return "class"
    if isinstance(node, ast.AsyncFunctionDef):
        return "async method" if inClass else "async function"
    if isinstance(node, ast.FunctionDef):
        return "method" if inClass else "function"
    if isinstance(node, _ASSIGNMENTS):
        return "attribute" if inClass else "variable"
    return "other"


def _assignedNames(node: ast.AST) -> list[str]:
    if isinstance(node, ast.AnnAssign):
        return [node.target.id] if isinstance(node.target, ast.Name) else []
    return [target.id for target in node.targets if isinstance(target, ast.Name)]


def _startLine(node: ast.AST) -> int:
    return min([node.lineno, *(decorator.lineno for decorator in getattr(node, "decorator_list", ()))])


def _toEntry(node: ast.AST, sourceLines: list[str], inClass: bool) -> dict | None:
    if isinstance(node, _DEFINITIONS):
        name = node.name
    elif isinstance(node, _ASSIGNMENTS):
        names = _assignedNames(node)
        if not names:
            return None
        name = ", ".join(names)
    else:
        return None
    return {
        "kind": _kindOf(node, inClass),
        "name": name,
        "line": _startLine(node),
        "endLine": getattr(node, "end_lineno", node.lineno),
        "signature": _signature(node, sourceLines),
        "docstring": _docstring(node),
    }


def _walk(
    node: ast.AST,
    sourceLines: list[str],
    inClass: bool,
    inFunction: bool,
    acc: list[dict],
) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _DEFINITIONS):
            entry = _toEntry(child, sourceLines, inClass)
            if entry is not None:
                acc.append(entry)
            isClass = isinstance(child, ast.ClassDef)
            _walk(child, sourceLines, isClass, inFunction or not isClass, acc)
            continue
        if isinstance(child, _ASSIGNMENTS):
            if not inFunction:
                entry = _toEntry(child, sourceLines, inClass)
                if entry is not None:
                    acc.append(entry)
            continue
        _walk(child, sourceLines, inClass, inFunction, acc)


@register_parser(".py")
class PythonParser(SourceParser):

    def listSymbols(self, sourceText: str) -> list[dict]:
        tree = ast.parse(sourceText)
        sourceLines = sourceText.splitlines()
        acc: list[dict] = []
        _walk(tree, sourceLines, False, False, acc)
        return acc
