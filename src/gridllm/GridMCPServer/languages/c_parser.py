import tree_sitter
import tree_sitter_c

from .base import SourceParser
from .parser_factory import register_parser

_LANGUAGE: tree_sitter.Language | None = None
_PARSER: tree_sitter.Parser | None = None

_TAGGED_KINDS = {
    "struct_specifier": "struct",
    "union_specifier": "union",
    "enum_specifier": "enum",
}

_MACRO_KINDS = ("preproc_def", "preproc_function_def")

_TRANSPARENT_KINDS = (
    "translation_unit",
    "preproc_if",
    "preproc_ifdef",
    "preproc_else",
    "preproc_elif",
    "preproc_elifdef",
    "linkage_specification",
    "declaration_list",
)

_DECLARATORS = (
    "function_declarator",
    "pointer_declarator",
    "array_declarator",
    "init_declarator",
    "parenthesized_declarator",
    "attributed_declarator",
)

_NAME_KINDS = ("identifier", "type_identifier", "field_identifier")


def _parser() -> tree_sitter.Parser:
    global _LANGUAGE, _PARSER
    if _PARSER is None:
        _LANGUAGE = tree_sitter.Language(tree_sitter_c.language())
        _PARSER = tree_sitter.Parser(_LANGUAGE)
    return _PARSER


def _text(node: tree_sitter.Node, sourceBytes: bytes) -> str:
    return sourceBytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _firstLine(text: str) -> str:
    return text.split("\n", 1)[0].strip()


def _child(node: tree_sitter.Node, *types: str) -> tree_sitter.Node | None:
    for child in node.children:
        if child.type in types:
            return child
    return None


def _nameOf(declarator: tree_sitter.Node, sourceBytes: bytes) -> str | None:
    node = declarator
    while node is not None and node.type in _DECLARATORS:
        node = node.child_by_field_name("declarator") or _child(node, *_DECLARATORS, *_NAME_KINDS)
    if node is not None and node.type in _NAME_KINDS:
        return _text(node, sourceBytes)
    return None


def _declaredName(node: tree_sitter.Node, sourceBytes: bytes) -> str | None:
    declarator = node.child_by_field_name("declarator")
    return _nameOf(declarator, sourceBytes) if declarator is not None else None


def _isFunction(declarator: tree_sitter.Node) -> bool:
    node = declarator
    while node is not None:
        if node.type == "function_declarator":
            return True
        if node.type not in _DECLARATORS:
            return False
        node = node.child_by_field_name("declarator")
    return False


def _docComment(node: tree_sitter.Node, sourceBytes: bytes) -> str | None:
    previous = node.prev_sibling
    if previous is None or previous.type != "comment":
        return None
    if previous.end_point.row + 1 < node.start_point.row:
        return None
    return _text(previous, sourceBytes).strip()


def _endLine(node: tree_sitter.Node) -> int:
    row = node.end_point.row + 1
    if node.end_point.column == 0 and row > node.start_point.row + 1:
        return row - 1
    return row


def _entry(node: tree_sitter.Node, sourceBytes: bytes, kind: str, name: str) -> dict:
    return {
        "kind": kind,
        "name": name,
        "line": node.start_point.row + 1,
        "endLine": _endLine(node),
        "signature": _firstLine(_text(node, sourceBytes)),
        "docstring": _docComment(node, sourceBytes),
    }


def _collectTagged(node: tree_sitter.Node, sourceBytes: bytes, acc: list[dict]) -> None:
    for child in node.children:
        kind = _TAGGED_KINDS.get(child.type)
        if kind is None:
            continue
        nameNode = child.child_by_field_name("name")
        if nameNode is not None:
            acc.append(_entry(child, sourceBytes, kind, _text(nameNode, sourceBytes)))
        body = child.child_by_field_name("body")
        if body is not None and child.type == "enum_specifier":
            _collectEnumerators(body, sourceBytes, acc)


def _collectEnumerators(body: tree_sitter.Node, sourceBytes: bytes, acc: list[dict]) -> None:
    for item in body.children:
        if item.type != "enumerator":
            continue
        nameNode = item.child_by_field_name("name")
        if nameNode is not None:
            acc.append(_entry(item, sourceBytes, "const", _text(nameNode, sourceBytes)))


def _collectDeclaration(node: tree_sitter.Node, sourceBytes: bytes, acc: list[dict]) -> None:
    _collectTagged(node, sourceBytes, acc)
    for declarator in node.children_by_field_name("declarator"):
        name = _nameOf(declarator, sourceBytes)
        if name:
            acc.append(_entry(node, sourceBytes, "prototype" if _isFunction(declarator) else "variable", name))


def _collectTypedef(node: tree_sitter.Node, sourceBytes: bytes, acc: list[dict]) -> None:
    _collectTagged(node, sourceBytes, acc)
    for declarator in node.children_by_field_name("declarator"):
        name = _nameOf(declarator, sourceBytes)
        if name:
            acc.append(_entry(node, sourceBytes, "typedef", name))


def _walk(node: tree_sitter.Node, sourceBytes: bytes, acc: list[dict]) -> None:
    for child in node.children:
        kind = child.type
        if kind == "function_definition":
            name = _declaredName(child, sourceBytes)
            if name:
                acc.append(_entry(child, sourceBytes, "function", name))
        elif kind == "type_definition":
            _collectTypedef(child, sourceBytes, acc)
        elif kind == "declaration":
            _collectDeclaration(child, sourceBytes, acc)
        elif kind in _MACRO_KINDS:
            nameNode = child.child_by_field_name("name")
            if nameNode is not None:
                acc.append(_entry(child, sourceBytes, "macro", _text(nameNode, sourceBytes)))
        elif kind in _TRANSPARENT_KINDS:
            _walk(child, sourceBytes, acc)


@register_parser(".c", ".h")
class CParser(SourceParser):

    def listSymbols(self, sourceText: str) -> list[dict]:
        sourceBytes = sourceText.encode("utf-8")
        tree = _parser().parse(sourceBytes)
        acc: list[dict] = []
        _walk(tree.root_node, sourceBytes, acc)
        return acc
