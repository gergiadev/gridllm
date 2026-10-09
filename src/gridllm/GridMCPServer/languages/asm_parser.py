import re

from .base import SourceParser
from .parser_factory import register_parser

_NAME = r"[.$@_A-Za-z][.$@_A-Za-z0-9]*"

_LABEL_RE = re.compile(rf"^\s*({_NAME})\s*:")

_MACRO_RE = re.compile(rf"^\s*\.macro\s+({_NAME})")

_ENDM_RE = re.compile(r"^\s*\.endm\b")

_EQU_RE = re.compile(rf"^\s*\.(?:equ|equiv|set)\s+({_NAME})\s*,\s*(.+)$", re.IGNORECASE)

_ASSIGN_RE = re.compile(rf"^\s*({_NAME})\s*=(?!=)\s*(.+)$")

_SECTION_RE = re.compile(rf"^\s*\.section\s+({_NAME})")

_SHORTHAND_SECTION_RE = re.compile(r"^\s*\.(text|data|bss|rodata)\b")

_GLOBAL_RE = re.compile(rf"^\s*\.(?:globl|global)\s+({_NAME})")

_DEFINE_RE = re.compile(rf"^\s*#\s*define\s+({_NAME})")

_LOCAL_PREFIX = ".L"

_SIZE_RE = re.compile(r"^\s*\.(?:size|endfunc|end)\b")

_COMMENT_RE = re.compile(
    r"^\s*("
    r"/[*].*[*]/"
    r"|/[*].*"
    r"|//.*"
    r"|\#(?!\s*define\b).*"
    r"|;.*"
    r"|@.*"
    r"|\*.*"
    r")\s*$"
)

_EMPTY_RE = re.compile(r"^\s*$")

_BOUNDARY_KINDS = frozenset({"label", "macro", "section"})

_COMMENT_MARKERS = ";#/*@"


def _isLineComment(line: str) -> bool:
    return bool(_EMPTY_RE.match(line)) or bool(_COMMENT_RE.match(line))


def _precedingComment(lines: list[str], startIdx: int) -> str | None:
    idx = startIdx - 1
    comments: list[str] = []
    while idx >= 0:
        current = lines[idx]
        if not current or current.isspace():
            idx -= 1
            continue
        if _COMMENT_RE.match(current):
            comments.append(current.strip().strip(_COMMENT_MARKERS).strip())
            idx -= 1
            continue
        break
    return "\n".join(reversed(comments)).strip() or None


def _entry(kind: str, name: str, line: int, signature: str, docstring: str | None) -> dict:
    return {
        "kind": kind,
        "name": name,
        "line": line,
        "endLine": line,
        "signature": signature,
        "docstring": docstring,
    }


def _scanLine(line: str, lineNum: int, lines: list[str], index: int) -> list[dict]:
    signature = line.strip()
    doc = _precedingComment(lines, index)
    found: list[dict] = []

    match = _DEFINE_RE.match(line) or _EQU_RE.match(line)
    if match:
        return [_entry("constant", match.group(1), lineNum, signature, doc)]

    match = _ASSIGN_RE.match(line)
    if match:
        return [_entry("constant", match.group(1), lineNum, signature, doc)]

    match = _SECTION_RE.match(line) or _SHORTHAND_SECTION_RE.match(line)
    if match:
        return [_entry("section", match.group(1), lineNum, signature, doc)]

    match = _GLOBAL_RE.match(line)
    if match:
        return [_entry("global", match.group(1), lineNum, signature, doc)]

    match = _LABEL_RE.match(line)
    if match:
        found.append(_entry("label", match.group(1), lineNum, signature, doc))

    return found


def _lastMeaningfulLine(lines: list[str]) -> int:
    for index in range(len(lines) - 1, -1, -1):
        if not _isLineComment(lines[index]):
            return index + 1
    return len(lines)


def _closeRanges(acc: list[dict], lines: list[str]) -> None:
    boundaries = sorted(
        entry["line"]
        for entry in acc
        if entry["kind"] in _BOUNDARY_KINDS and not entry["name"].startswith(_LOCAL_PREFIX)
    )
    terminators = sorted(
        index + 1 for index, line in enumerate(lines) if _SIZE_RE.match(line)
    )
    end = _lastMeaningfulLine(lines)

    for entry in acc:
        if entry["kind"] != "label":
            continue
        start = entry["line"]
        stops = [value - 1 for value in boundaries if value > start]
        stops.extend(value for value in terminators if value > start)
        entry["endLine"] = min([*stops, end]) if stops else end
        entry["endLine"] = max(entry["endLine"], start)


def _parseAssembly(sourceText: str) -> list[dict]:
    lines = sourceText.splitlines()
    acc: list[dict] = []
    macroStart = 0
    macroName = ""
    macroDoc: str | None = None
    inMacro = False

    for index, line in enumerate(lines):
        lineNum = index + 1

        if _isLineComment(line):
            continue

        if inMacro:
            if _ENDM_RE.match(line):
                entry = _entry("macro", macroName, macroStart, f".macro {macroName}", macroDoc)
                entry["endLine"] = lineNum
                acc.append(entry)
                inMacro = False
            continue

        match = _MACRO_RE.match(line)
        if match:
            inMacro = True
            macroStart = lineNum
            macroName = match.group(1)
            macroDoc = _precedingComment(lines, index)
            continue

        acc.extend(_scanLine(line, lineNum, lines, index))

    if inMacro:
        entry = _entry("macro", macroName, macroStart, f".macro {macroName}", macroDoc)
        entry["endLine"] = _lastMeaningfulLine(lines)
        acc.append(entry)

    _closeRanges(acc, lines)
    return sorted(acc, key=lambda entry: entry["line"])


@register_parser(".s", ".asm", ".S")
class AsmParser(SourceParser):

    def listSymbols(self, sourceText: str) -> list[dict]:
        return _parseAssembly(sourceText)
