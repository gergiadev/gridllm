import re

import tree_sitter
import tree_sitter_php

from .base import SourceParser
from .parser_factory import register_parser

_LANGUAGE: tree_sitter.Language | None = None
_PARSER: tree_sitter.Parser | None = None

_NAMED_KINDS = {
    "function_definition": "function",
    "method_declaration": "method",
    "class_declaration": "class",
    "interface_declaration": "interface",
    "trait_declaration": "trait",
}

_LEAF_KINDS = ("function_definition", "method_declaration")

_CONTAINER_KINDS = ("class_declaration", "interface_declaration", "trait_declaration")

_PATTERN_KINDS = {
    "const_declaration": ("const", r"const\s+([A-Za-z_][A-Za-z0-9_]*)"),
    "property_declaration": ("property", r"\$([A-Za-z_][A-Za-z0-9_]*)"),
    "use_declaration": ("use", r"use\s+([A-Za-z_\\][A-Za-z0-9_\\]*)"),
}


def _parser() -> tree_sitter.Parser:
    global _LANGUAGE, _PARSER
    if _PARSER is None:
        _LANGUAGE = tree_sitter.Language(tree_sitter_php.language_php())
        _PARSER = tree_sitter.Parser(_LANGUAGE)
    return _PARSER


def _nodeText(node: tree_sitter.Node, sourceBytes: bytes) -> str:
    return sourceBytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _nodeLine(node: tree_sitter.Node) -> int:
    return node.start_point.row + 1


def _nodeEndLine(node: tree_sitter.Node) -> int:
    return node.end_point.row + 1


def _firstLine(text: str) -> str:
    return text.split("\n", 1)[0].strip()


def _byName(node: tree_sitter.Node, name: str) -> tree_sitter.Node | None:
    for child in node.children:
        if child.type == name:
            return child
    return None


def _docComment(node: tree_sitter.Node, sourceBytes: bytes) -> str | None:
    prev = node.prev_sibling
    if prev is None or prev.type != "comment":
        return None
    text = _nodeText(prev, sourceBytes).strip()
    return text if text.startswith("/**") else None


def _collectEntry(
    node: tree_sitter.Node,
    sourceBytes: bytes,
    kind: str,
    name: str,
    acc: list[dict],
) -> None:
    text = _nodeText(node, sourceBytes)
    acc.append({
        "kind": kind,
        "name": name,
        "line": _nodeLine(node),
        "endLine": _nodeEndLine(node),
        "signature": _firstLine(text),
        "docstring": _docComment(node, sourceBytes),
    })


def _collectNamed(node: tree_sitter.Node, sourceBytes: bytes, kind: str, acc: list[dict]) -> None:
    nameNode = _byName(node, "name")
    if nameNode is not None:
        _collectEntry(node, sourceBytes, kind, _nodeText(nameNode, sourceBytes), acc)


def _walkFunctions(
    node: tree_sitter.Node,
    sourceBytes: bytes,
    inClass: bool,
    acc: list[dict],
) -> None:
    kind = node.type

    if kind in _LEAF_KINDS:
        _collectNamed(node, sourceBytes, "method" if inClass else _NAMED_KINDS[kind], acc)
        return

    if kind in _CONTAINER_KINDS:
        _collectNamed(node, sourceBytes, _NAMED_KINDS[kind], acc)
    elif kind in _PATTERN_KINDS:
        label, pattern = _PATTERN_KINDS[kind]
        match = re.search(pattern, _nodeText(node, sourceBytes))
        if match:
            _collectEntry(node, sourceBytes, label, match.group(1), acc)

    newInClass = inClass or kind in _CONTAINER_KINDS
    for child in node.children:
        _walkFunctions(child, sourceBytes, newInClass, acc)


def _walkGlobalVars(
    node: tree_sitter.Node,
    sourceBytes: bytes,
    acc: list[dict],
) -> None:
    if node.type == "expression_statement":
        for child in node.children:
            if child.type == "assignment_expression" and child.children:
                left = child.children[0]
                if left.type == "variable_name":
                    text = _nodeText(left, sourceBytes)
                    match = re.match(r"\$([A-Za-z_][A-Za-z0-9_]*)", text)
                    if match:
                        _collectEntry(node, sourceBytes, "variable", match.group(1), acc)
    for child in node.children:
        _walkGlobalVars(child, sourceBytes, acc)


@register_parser(".php")
class PhpParser(SourceParser):

    def listSymbols(self, sourceText: str) -> list[dict]:
        sourceBytes = sourceText.encode("utf-8")
        tree = _parser().parse(sourceBytes)
        acc: list[dict] = []
        _walkFunctions(tree.root_node, sourceBytes, False, acc)
        _walkGlobalVars(tree.root_node, sourceBytes, acc)
        return acc