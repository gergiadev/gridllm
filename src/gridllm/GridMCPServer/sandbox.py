import asyncio
import shutil
import subprocess
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path

from .workspace import isIgnored

PREFIX = "gridllm-sandbox-"

ARTIFACT_SUFFIXES = frozenset({
    ".o", ".a", ".so", ".d", ".obj", ".exe", ".gch", ".pch", ".lo", ".la", ".pyc", ".pyo", ".elf", ".bin", ".map",
})


class Sandbox:

    def __init__(self, workspace: Path, ignore: Iterable[str] = ()) -> None:
        self.workspace = workspace
        self.ignore = tuple(ignore)
        self.root: Path | None = None
        self._lock = asyncio.Lock()

    async def path(self) -> Path:
        async with self._lock:
            if self.root is None:
                self.root = await asyncio.to_thread(self._build)
            return self.root

    def _build(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix=PREFIX))
        shutil.copytree(
            self.workspace,
            root,
            symlinks=True,
            ignore=shutil.ignore_patterns(*self.ignore),
            dirs_exist_ok=True,
        )
        return root

    async def invalidate(self) -> None:
        async with self._lock:
            stale, self.root = self.root, None
        if stale is not None:
            await asyncio.to_thread(shutil.rmtree, stale, True)

    def remove(self) -> None:
        stale, self.root = self.root, None
        if stale is not None:
            shutil.rmtree(stale, ignore_errors=True)


def tracked(root: Path) -> set[str] | None:
    try:
        outcome = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=str(root), capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if outcome.returncode != 0:
        return None
    names = [name for name in outcome.stdout.split("\0") if name]
    return {(root / name).as_posix() for name in names} or None


def snapshot(root: Path, ignore: Iterable[str], keep: set[str] | None = None) -> dict[str, tuple[int, int]]:
    seen: dict[str, tuple[int, int]] = {}
    for item in root.rglob("*"):
        if isIgnored(item, root, ignore):
            continue
        if keep is not None and item.as_posix() not in keep:
            continue
        if keep is None and item.suffix.lower() in ARTIFACT_SUFFIXES:
            continue
        try:
            stat = item.stat()
        except OSError:
            continue
        if not item.is_file():
            continue
        seen[item.as_posix()] = (stat.st_mtime_ns, stat.st_size)
    return seen


def modified(before: Mapping[str, tuple[int, int]], after: Mapping[str, tuple[int, int]]) -> list[str]:
    return sorted(path for path, meta in after.items() if path in before and before[path] != meta)
