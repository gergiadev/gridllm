import asyncio
import re
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path

from .workspace import walk

PREFIX = "gridllm-sandbox-"

SLUG = re.compile(r"[^A-Za-z0-9_.-]+")

ARTIFACT_SUFFIXES = frozenset({
    ".o", ".a", ".so", ".d", ".obj", ".exe", ".gch", ".pch", ".lo", ".la", ".pyc", ".pyo", ".elf", ".bin", ".map",
})


def _slug(owner: str) -> str:
    return SLUG.sub("_", owner)[:32] or "anon"


class Sandbox:

    def __init__(self, workspace: Path, ignore: Iterable[str] = ()) -> None:
        self.workspace = workspace
        self.ignore = tuple(ignore)
        self.roots: dict[str, Path] = {}
        self._lock = asyncio.Lock()

    async def path(self, owner: str) -> Path:
        async with self._lock:
            root = self.roots.get(owner)
            if root is None:
                root = await asyncio.to_thread(self._build, owner)
                self.roots[owner] = root
            return root

    def _build(self, owner: str) -> Path:
        root = Path(tempfile.mkdtemp(prefix=f"{PREFIX}{_slug(owner)}-"))
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
            stale, self.roots = list(self.roots.values()), {}
        for root in stale:
            await asyncio.to_thread(shutil.rmtree, root, True)

    def remove(self) -> None:
        stale, self.roots = list(self.roots.values()), {}
        for root in stale:
            shutil.rmtree(root, ignore_errors=True)


def snapshot(root: Path, ignore: Iterable[str]) -> dict[str, tuple[int, int]]:
    seen: dict[str, tuple[int, int]] = {}
    for item in walk(root, root, ignore):
        if item.suffix.lower() in ARTIFACT_SUFFIXES:
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
    changed = set(before) ^ set(after)
    changed.update(path for path in set(before) & set(after) if before[path] != after[path])
    return sorted(changed)
