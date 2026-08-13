import os
import tempfile
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path

from mcp import MCPError
from mcp.types import INVALID_PARAMS

ROOT_ALIASES = ("", ".", "./", ".\\", "/", "*", "**")


def _normalize(workspace: Path, path: str) -> str:
    cleaned = str(path).strip().strip('"').strip("'")
    if cleaned in ROOT_ALIASES:
        return "."

    root = str(workspace)
    if cleaned == root:
        return "."
    if cleaned.startswith(f"{root}/"):
        return cleaned[len(root) + 1:] or "."
    if cleaned.startswith("/"):
        return cleaned.lstrip("/") or "."
    if cleaned.startswith("./"):
        return cleaned[2:] or "."
    return cleaned


def resolveSafe(workspace: Path, path: str) -> Path:
    relative = _normalize(workspace, path)
    try:
        target = (workspace / relative).resolve(strict=False)
    except OSError as exc:
        raise MCPError(INVALID_PARAMS, f"invalid path: {exc}") from exc
    if target != workspace and workspace not in target.parents:
        raise MCPError(INVALID_PARAMS, f"path outside the workspace: {path}")
    return target


def relPath(target: Path, root: Path) -> str:
    try:
        return target.relative_to(root).as_posix()
    except ValueError:
        return target.name


def isIgnored(target: Path, root: Path, patterns: Iterable[str]) -> bool:
    parts = Path(relPath(target, root)).parts
    return any(fnmatch(part, pattern) for part in parts for pattern in patterns)


def statEntry(target: Path) -> dict:
    stat = target.stat()
    return {
        "path": target.name,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "isDir": target.is_dir(),
    }


def writeAtomic(target: Path, content: str) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmpPath = tempfile.mkstemp(
        prefix=".tmp_",
        dir=str(target.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmpPath, target)
    except Exception:
        try:
            os.unlink(tmpPath)
        except OSError:
            pass
        raise
    return len(content)
