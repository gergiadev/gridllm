import os
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path

from .workspace import isIgnored

RTK = "rtk"
RG = "rg"
GREP = "grep"
EGREP = "egrep"
DEFAULT_SUBPROCESS_TIMEOUT = 30


def _buildEntry(item: Path, root: Path, stat: os.stat_result) -> dict:
    return {
        "path": item.relative_to(root).as_posix(),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "isDir": item.is_dir(),
    }


def _ensureWithin(path: Path, maxBytes: int) -> None:
    size = path.stat().st_size
    if size > maxBytes:
        raise ValueError(f"file too large: {size} bytes (max {maxBytes})")


class Reader(ABC):

    def __init__(self, ignore: Iterable[str] = ()) -> None:
        self.ignore = tuple(ignore)

    def keep(self, path: Path, root: Path) -> bool:
        return not isIgnored(path, root, self.ignore)

    @abstractmethod
    def read(self, path: Path, maxBytes: int) -> str:
        ...

    @abstractmethod
    def listing(self, base: Path, root: Path) -> list[dict]:
        ...

    @abstractmethod
    def search(self, query: str, base: Path, root: Path, isRegex: bool) -> list[dict]:
        ...


class NativeReader(Reader):

    def read(self, path: Path, maxBytes: int) -> str:
        _ensureWithin(path, maxBytes)
        return path.read_text(encoding="utf-8")

    def listing(self, base: Path, root: Path) -> list[dict]:
        if base.is_file():
            return [_buildEntry(base, root, base.stat())]

        entries: list[dict] = []
        for item in sorted(base.rglob("*")):
            if not self.keep(item, root):
                continue
            try:
                stat = item.stat()
            except OSError:
                continue
            if not item.is_file() and not item.is_dir():
                continue
            entries.append(_buildEntry(item, root, stat))
        return entries

    def search(self, query: str, base: Path, root: Path, isRegex: bool) -> list[dict]:
        pattern = re.compile(query) if isRegex else re.compile(re.escape(query))
        results: list[dict] = []
        for file in sorted(base.rglob("*")):
            if not file.is_file() or not self.keep(file, root):
                continue
            try:
                text = file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    results.append({
                        "path": file.relative_to(root).as_posix(),
                        "line": number,
                        "text": line,
                    })
        return results


class _GrepReader(Reader):

    def __init__(self, ignore: Iterable[str] = (), timeout: int = DEFAULT_SUBPROCESS_TIMEOUT) -> None:
        super().__init__(ignore)
        self.timeout = timeout
        self.native = NativeReader(ignore)

    def read(self, path: Path, maxBytes: int) -> str:
        _ensureWithin(path, maxBytes)
        return path.read_text(encoding="utf-8")

    def listing(self, base: Path, root: Path) -> list[dict]:
        return self.native.listing(base, root)

    def _parse(self, stdout: str, root: Path) -> list[dict]:
        return [entry for entry in _parseGrepOutput(stdout, root) if self.keep(root / entry["path"], root)]


class RipgrepReader(_GrepReader):

    def search(self, query: str, base: Path, root: Path, isRegex: bool) -> list[dict]:
        args = [RG, "--no-heading", "-n", "--color", "never"]
        if not isRegex:
            args.append("-F")
        args.extend([query, str(base)])
        try:
            outcome = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return self.native.search(query, base, root, isRegex)
        if outcome.returncode not in (0, 1):
            return self.native.search(query, base, root, isRegex)
        return self._parse(outcome.stdout, root)


class GrepReader(_GrepReader):

    def search(self, query: str, base: Path, root: Path, isRegex: bool) -> list[dict]:
        binary = EGREP if isRegex else GREP
        args = [binary, "-rn", "--color=never"]
        if not isRegex:
            args.append("-F")
        args.extend([query, str(base)])
        try:
            outcome = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return self.native.search(query, base, root, isRegex)
        if outcome.returncode not in (0, 1):
            return self.native.search(query, base, root, isRegex)
        return self._parse(outcome.stdout, root)


def _parseGrepOutput(stdout: str, root: Path) -> list[dict]:
    results: list[dict] = []
    for line in stdout.splitlines():
        sep = line.find(":")
        if sep < 0:
            continue
        path_part = line[:sep]
        rest = line[sep + 1:]
        sep2 = rest.find(":")
        if sep2 < 0:
            continue
        try:
            line_num = int(rest[:sep2])
        except ValueError:
            continue
        text = rest[sep2 + 1:]
        try:
            rel = Path(path_part).relative_to(root).as_posix()
        except ValueError:
            rel = path_part
        results.append({"path": rel, "line": line_num, "text": text})
    return results


class RtkReader(Reader):

    def __init__(self, ignore: Iterable[str] = (), timeout: int = DEFAULT_SUBPROCESS_TIMEOUT) -> None:
        super().__init__(ignore)
        self.timeout = timeout
        self.native = NativeReader(ignore)

    def read(self, path: Path, maxBytes: int) -> str:
        _ensureWithin(path, maxBytes)
        return self._run(["read", str(path)])

    def listing(self, base: Path, root: Path) -> list[dict]:
        return self.native.listing(base, root)

    def search(self, query: str, base: Path, root: Path, isRegex: bool) -> list[dict]:
        return self.native.search(query, base, root, isRegex)

    def _run(self, args: list[str]) -> str:
        outcome = subprocess.run(
            [RTK, *args],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if outcome.returncode != 0:
            raise ValueError(outcome.stderr.strip() or f"{RTK} {args[0]}: failed")
        return outcome.stdout.strip()


def choose_reader(logger, timeout: int = DEFAULT_SUBPROCESS_TIMEOUT, ignore: Iterable[str] = ()) -> Reader:
    rg_path = shutil.which(RG)
    grep_path = shutil.which(GREP)
    rtk_path = shutil.which(RTK)

    if rtk_path:
        logger.info("%s found at %s: preferred for file reading", RTK, rtk_path)
        reader = RtkReader(ignore, timeout=timeout)
    else:
        logger.info("%s not available: using native reading", RTK)
        reader = NativeReader(ignore)

    if rg_path:
        logger.info("%s found at %s: preferred for search", RG, rg_path)
        reader.search = RipgrepReader(ignore, timeout=timeout).search  # type: ignore[method-assign]
    elif grep_path:
        logger.info("%s found at %s: fallback for search", GREP, grep_path)
        reader.search = GrepReader(ignore, timeout=timeout).search  # type: ignore[method-assign]
    else:
        logger.info("neither %s nor %s available: using native search", RG, GREP)

    return reader