import re
import shutil

RTK = "rtk"

RTK_COMMANDS = {
    "ls": "ls",
    "tree": "tree",
    "find": "find",
    "grep": "grep",
    "rg": "rg",
    "wc": "wc",
    "git": "git",
}

SEPARATORS = ("&&", "||")
BREAK_CHARS = "|&;()"
REDIRECT_CHARS = "<>"
QUOTE_CHARS = "'\""
LEADING = re.compile(r"(\s*)([A-Za-z0-9_./+-]+)(?=\s|$)")


def rtkAvailable() -> bool:
    return shutil.which(RTK) is not None


def _scan(command: str) -> tuple[list[tuple[str, bool]], bool]:
    pieces: list[tuple[str, bool]] = []
    buffer: list[str] = []
    quote = ""
    eligible = True
    index = 0
    total = len(command)
    while index < total:
        char = command[index]
        if quote:
            buffer.append(char)
            if char == "\\" and quote == '"' and index + 1 < total:
                buffer.append(command[index + 1])
                index += 2
                continue
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in QUOTE_CHARS:
            quote = char
            buffer.append(char)
            index += 1
            continue
        if char == "\\" and index + 1 < total:
            buffer.append(char)
            buffer.append(command[index + 1])
            index += 2
            continue
        if char in REDIRECT_CHARS:
            eligible = False
            buffer.append(char)
            index += 1
            continue
        if char in BREAK_CHARS:
            token = command[index:index + 2]
            if token not in SEPARATORS:
                token = char
            pieces.append(("".join(buffer), eligible))
            pieces.append((token, False))
            buffer = []
            eligible = True
            index += len(token)
            continue
        buffer.append(char)
        index += 1
    if quote:
        return [], False
    pieces.append(("".join(buffer), eligible))
    return pieces, True


def _rewriteSegment(segment: str) -> str:
    match = LEADING.match(segment)
    if not match:
        return segment
    target = RTK_COMMANDS.get(match.group(2))
    if target is None:
        return segment
    return f"{match.group(1)}{RTK} {target}{segment[match.end(2):]}"


def rewriteCommand(command: str) -> str:
    pieces, ok = _scan(command)
    if not ok:
        return command
    return "".join(_rewriteSegment(text) if eligible else text for text, eligible in pieces)
