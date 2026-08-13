import re

from .base import SourceParser
from .parser_factory import register_parser

_LABEL_RE = re.compile(
    r"^\s*"
    r"([.@_A-Za-z][.@_A-Za-z0-9]*)\s*:"
    r"\s*"
    r"("
    r"/[/*].*"          # ARM-style comment
    r"|//.*"            # C++ comment
    r"|\#.*"            # ARM/Linux comment
    r"|;.*"             # x86 comment
    r"|@.*"             # ARM alternate comment
    r"|\*.*"            # ARM code comment
    r")?"
    r"\s*$",
)

_INSTRUCTION_RE = re.compile(
    r"^\s*"
    r"([.@_A-Za-z][.@_A-Za-z0-9]*)"  # mnemonic or directive
    r"(?:\s+"
    r"(.*?)"                         # operands (non-greedy)
    r")?"
    r"\s*$",
)

_EQU_RE = re.compile(
    r"^\s*"
    r"([.@_A-Za-z][.@_A-Za-z0-9]*)"  # name
    r"\s*"
    r"(?:=|\.\s*equ\s+|\.\s*set\s+)"  # = or .equ or .set
    r"(.*)"
    r"\s*$",
)

_SECTION_RE = re.compile(
    r"^\s*\.section\s+([.@_A-Za-z][._@A-Za-z0-9]*)"
)

_MACRO_RE = re.compile(
    r"^\s*\.macro\s+([.@_A-Za-z][.@_A-Za-z0-9]*)"
)

_COMMENT_RE = re.compile(
    r"^\s*"
    r"("
    r"/[*].*[*]/"       # block comment
    r"|//.*"            # line comment
    r"|\#.*"            # ARM/Linux
    r"|;.*"             # x86
    r"|@\s"             # ARM inline comment
    r"|\*.*"            # ARM code comment
    r")"
    r"\s*$",
)

_EMPTY_RE = re.compile(r"^\s*$")

_ENDP_RE = re.compile(r"\.endm|\.endr|\.end|\.endfunc")


def _isLineComment(line: str) -> bool:
    return bool(_EMPTY_RE.match(line)) or bool(_COMMENT_RE.match(line))


def _precedingComment(lines: list[str], startIdx: int) -> str | None:
    idx = startIdx - 1
    comments: list[str] = []
    while idx >= 0:
        stripped = lines[idx]
        if not stripped or stripped.isspace():
            idx -= 1
            continue
        if _COMMENT_RE.match(stripped):
            comments.append(stripped.strip(";").strip("#").strip("/").strip("*").strip())
            idx -= 1
            continue
        break
    return "\n".join(reversed(comments)).strip() or None


def _parseAssembly(sourceText: str) -> list[dict]:
    lines = sourceText.splitlines()
    acc: list[dict] = []
    inMacro = False
    macroStart = 0
    macroName = ""

    for i, line in enumerate(lines):
        lineNum = i + 1
        stripped = line

        if _isLineComment(stripped):
            continue

        m = _MACRO_RE.match(stripped)
        if m:
            inMacro = True
            macroStart = lineNum
            macroName = m.group(1)
            continue

        if inMacro:
            if _ENDP_RE.search(stripped):
                acc.append({
                    "kind": "macro",
                    "name": macroName,
                    "line": macroStart,
                    "endLine": lineNum,
                    "signature": f".macro {macroName}",
                    "docstring": None,
                })
                inMacro = False
            continue

        m = _EQU_RE.match(stripped)
        if m:
            acc.append({
                "kind": "constant",
                "name": m.group(1),
                "line": lineNum,
                "endLine": lineNum,
                "signature": stripped.strip(),
                "docstring": _precedingComment(lines, i),
            })
            continue

        m = _LABEL_RE.match(stripped)
        if m:
            acc.append({
                "kind": "label",
                "name": m.group(1),
                "line": lineNum,
                "endLine": lineNum,
                "signature": stripped.strip(),
                "docstring": _precedingComment(lines, i),
            })
            continue

        m = _INSTRUCTION_RE.match(stripped)
        if m:
            mnemonic = m.group(1)
            if mnemonic.startswith("."):
                kind = "directive"
            else:
                kind = "instruction"

            acc.append({
                "kind": kind,
                "name": mnemonic,
                "line": lineNum,
                "endLine": lineNum,
                "signature": stripped.strip(),
                "docstring": _precedingComment(lines, i),
            })

    return acc


def _bodyForSymbol(sourceText: str, symbolName: str) -> list[dict]:
    lines = sourceText.splitlines()
    symbols = _parseAssembly(sourceText)
    results: list[dict] = []
    for s in symbols:
        if s["name"] != symbolName:
            continue
        start = s["line"]
        end = s["endLine"]
        if start <= 0 or end < start:
            continue
        results.append({
            "kind": s["kind"],
            "name": s["name"],
            "line": start,
            "endLine": end,
            "body": "\n".join(lines[start - 1:end]),
        })
    return results


@register_parser(".s", ".asm", ".S")
class AsmParser(SourceParser):

    def listSymbols(self, sourceText: str) -> list[dict]:
        return _parseAssembly(sourceText)

    def getSymbolBody(self, sourceText: str, symbolName: str) -> list[dict]:
        return _bodyForSymbol(sourceText, symbolName)
