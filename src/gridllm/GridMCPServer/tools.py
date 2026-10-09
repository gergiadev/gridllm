import asyncio
import functools
import os
import shutil
import signal
from collections.abc import Callable, Iterable
from pathlib import Path

from mcp import MCPError
from mcp.types import INVALID_PARAMS

from .errors import mapError
from .formatting import formatEntries, formatEntry
from .languages import SourceParser, choose_parser, supported_extensions
from .permissions import CURRENT_ACCESS, CURRENT_AGENT, READ_WRITE
from .readers import Reader
from .rtkshell import RTK, RTK_COMMANDS, rewriteCommand, rtkAvailable
from .sandbox import Sandbox, modified, snapshot
from .workspace import (
    expandBraces,
    readLines,
    relPath,
    resolveSafe,
    statEntry,
    walk,
    writeAtomic,
)

GIT = "git"

GIT_TIMEOUT = 30


async def _terminateGroup(proc) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
    await proc.wait()


def capped(fn: Callable, limit: int) -> Callable:
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        output = await fn(*args, **kwargs)
        if limit <= 0 or len(output) <= limit:
            return output
        return (
            f"{output[:limit]}\n\n"
            f"[output truncated: {len(output) - limit} of {len(output)} characters omitted; "
            f"narrow the request and read again]"
        )

    return wrapper


class Tools:

    def __init__(
        self,
        workspace: Path,
        reader: Reader,
        maxBytes: int,
        shellTimeout: int = 60,
        ignore: Iterable[str] = (),
        logger=None,
        sandbox: Sandbox | None = None,
        scope=None,
        secretEnv: Iterable[str] = (),
    ):
        self.workspace = workspace
        self.reader = reader
        self.maxBytes = maxBytes
        self.shellTimeout = shellTimeout
        self.ignore = tuple(ignore)
        self.logger = logger
        self.sandbox = sandbox
        self.scope = scope
        self.secretEnv = frozenset(secretEnv)
        self.rtk = rtkAvailable()
        if logger:
            if self.rtk:
                logger.info("%s available: shell proxies %s", RTK, ", ".join(sorted(RTK_COMMANDS)))
            else:
                logger.info("%s not available: shell commands run natively", RTK)

    def _collectSourceFiles(self, target: Path) -> list[Path]:
        extensions = supported_extensions()
        if not target.exists():
            raise MCPError(INVALID_PARAMS, f"no such file or directory: {relPath(target, self.workspace)}")
        if target.is_file():
            if target.suffix.lower() not in extensions:
                raise MCPError(
                    INVALID_PARAMS,
                    f"unsupported language for {target.suffix} (supported: {', '.join(extensions)})",
                )
            return [target]
        return [
            path
            for path in walk(target, self.workspace, self.ignore)
            if path.suffix.lower() in extensions and path.is_file()
        ]

    async def _offload(self, fn: Callable, *args):
        try:
            return await asyncio.to_thread(fn, *args)
        except Exception as exc:
            raise mapError(exc) from exc

    async def list_files(self, subdir: str = ".") -> str:
        """List every file and directory under subdir, recursively.

        Use this first to discover the layout of the codebase.

        subdir: directory relative to the workspace root; defaults to the whole workspace.

        Returns one JSON object per line with the keys "path" (relative to the
        workspace root, usable directly with read_file), "size" in bytes,
        "mtime" as a unix timestamp and "isDir". Returns "(no files)" if empty.
        """
        target = resolveSafe(self.workspace, subdir)
        if not target.exists():
            raise MCPError(INVALID_PARAMS, f"no such directory: {subdir}")
        entries = await self._offload(self.reader.listing, target, self.workspace)
        return formatEntries(entries, "(no files)")

    async def read_file(self, path: str, offset: int = 0, limit: int = 0) -> str:
        """Read the text content of a file.

        Prefer get_symbol_body when you only need one function or class from a
        large source file: it returns far less text.

        path: file relative to the workspace root.
        offset: 1-based line number to start reading from (0 or 1 means beginning).
        limit: maximum number of lines to return (0 means no limit).

        Fails if path is a directory, does not exist or is not valid UTF-8. A
        file larger than the configured size limit can only be read through
        offset and limit.
        """
        target = resolveSafe(self.workspace, path)
        if target.is_dir():
            raise MCPError(INVALID_PARAMS, f"is a directory, not a file: {path}")
        if offset <= 1 and limit <= 0:
            return await self._offload(self.reader.read, target, self.maxBytes)
        start = max(0, offset - 1)
        selected, total = await self._offload(readLines, target, start, limit)
        if not selected:
            last = start + limit if limit > 0 else total
            return f"(lines {start + 1}-{last} out of range; file has {total} lines)"
        return "\n".join(selected)

    async def write_file(self, path: str, content: str) -> str:
        """Create a file, or replace an existing one, with content.

        The whole file is overwritten, so pass its complete new text. To change
        part of an existing file use edit_file instead. The write is atomic and
        missing parent directories are created.

        path: file relative to the workspace root.
        content: the complete text to write.

        Fails if content exceeds the configured size limit.
        """
        target = resolveSafe(self.workspace, path)
        if len(content.encode("utf-8")) > self.maxBytes:
            raise MCPError(INVALID_PARAMS, f"content too large: max {self.maxBytes} bytes")
        written = await self._offload(writeAtomic, target, content)
        await self._invalidateSandbox()
        return f"wrote {written} characters to {path}"

    async def edit_file(self, path: str, oldString: str, newString: str) -> str:
        """Replace one exact occurrence of oldString with newString in a file.

        oldString must match the file byte for byte, indentation included, and
        must occur exactly once: include enough surrounding lines to make it
        unique. The edit is rejected if it matches zero times or more than once,
        so nothing is ever changed ambiguously.

        path: file relative to the workspace root.
        oldString: exact text to find, unique within the file.
        newString: text to put in its place; empty to delete.
        """
        target = resolveSafe(self.workspace, path)
        current = await self._offload(target.read_text, "utf-8")
        count = current.count(oldString)
        if count == 0:
            raise MCPError(INVALID_PARAMS, "oldString not found in the file")
        if count > 1:
            raise MCPError(INVALID_PARAMS, f"oldString occurs {count} times: it must be unique")
        updated = current.replace(oldString, newString, 1)
        if len(updated.encode("utf-8")) > self.maxBytes:
            raise MCPError(INVALID_PARAMS, f"result too large: max {self.maxBytes} bytes")
        await self._offload(writeAtomic, target, updated)
        await self._invalidateSandbox()
        return f"edited {path}"

    async def search_content(self, query: str, subdir: str = ".", isRegex: bool = False, include: str = "") -> str:
        """Search for text across every file under subdir, line by line.

        Use this to locate code by content. To locate it by symbol name,
        find_symbol is faster and more precise.

        query: literal text to find, or a Python regular expression if isRegex.
        subdir: directory relative to the workspace root; defaults to the whole workspace.
        isRegex: treat query as a regular expression instead of literal text.
        include: optional glob pattern restricting which files are searched, matched
            against both the path relative to the workspace root and the bare file
            name. Brace alternatives are expanded, so "*.{c,h,s}" searches C sources
            and headers and assembly, "*.py" only Python, "src/**/*.c" only C files
            under src. Empty means every file.

        Returns one JSON object per line with "path" (relative to the workspace
        root, usable directly with read_file), the 1-based "line" number and the
        matching "text". Returns "(no matches)" if nothing matches.
        """
        if not query:
            raise MCPError(INVALID_PARAMS, "empty query")
        target = resolveSafe(self.workspace, subdir)
        patterns = tuple(expandBraces(include)) if include else ()
        results = await self._offload(
            self.reader.search, query, target, self.workspace, isRegex, patterns
        )
        return formatEntries(results, "(no matches)")

    async def stat(self, path: str) -> str:
        """Report metadata for a single file or directory.

        Use it to check whether something exists, how big it is, or whether it
        is a directory, without reading its content.

        path: file or directory relative to the workspace root.

        Returns one JSON object with "path" (the bare name, not the path you
        passed), "size" in bytes, "mtime" as a unix timestamp and "isDir".
        """
        target = resolveSafe(self.workspace, path)
        entry = await self._offload(statEntry, target)
        return formatEntry(entry)

    async def shell(self, command: str, workdir: str = ".") -> str:
        """Run a shell command and return its output.

        Use this to compile code, run tests, inspect binaries, or check tool
        availability. The command runs in a subprocess with a timeout.

        If your access is read-only the command runs against a throwaway copy of
        the workspace that belongs to you alone, not the workspace itself. Build
        it, edit it, break it: nothing you do there reaches the real files, no
        other agent sees it, and it keeps its state between your commands so a
        build followed by a test works. Because of that, never report a file as
        changed on the strength of a shell command alone. The copy carries no
        git history, so git commands do not work inside it: use git_diff,
        git_log and git_blame, which always read the real workspace.

        If your access is read-write the command runs against the real workspace.
        Files the verdict does not allow you to write must be exactly as you found
        them when the command ends: creating, deleting or modifying any of them is
        reported back to you as a warning and has to be undone.

        command: the shell command to execute.
        workdir: subdirectory of the workspace to run in; defaults to the workspace root.

        Inspection commands (ls, tree, find, grep, rg, wc, git) may be answered in a
        condensed layout that carries the same information in fewer tokens, so do not
        expect output byte-identical to the native tool.

        Returns the combined stdout and stderr output. The return code is included
        at the end as "EXIT: N". Fails if the command times out.
        """
        target = resolveSafe(self.workspace, workdir)
        if target.is_file():
            target = target.parent
        root, confined = await self._shellRoot()
        target = root / target.relative_to(self.workspace)
        if not target.is_dir():
            target = root
        effective = rewriteCommand(command) if self.rtk else command
        if self.logger and effective != command:
            self.logger.info("shell via %s: %s", RTK, effective)
        before = None if confined else self._auditBefore()
        try:
            proc = await asyncio.create_subprocess_shell(
                effective,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(target),
                env={key: value for key, value in os.environ.items() if key not in self.secretEnv},
                start_new_session=True,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self.shellTimeout)
            except TimeoutError:
                await _terminateGroup(proc)
                raise MCPError(
                    INVALID_PARAMS,
                    f"command timed out after {self.shellTimeout}s: {command[:80]}",
                )
            output = stdout.decode("utf-8", errors="replace").strip()
            report = (output or "(no output)") + f"\n\nEXIT: {proc.returncode}"
            return report + self._auditAfter(before)
        except OSError as exc:
            raise MCPError(INVALID_PARAMS, f"failed to run command: {exc}")

    async def _invalidateSandbox(self) -> None:
        if self.sandbox is not None:
            await self.sandbox.invalidate()

    async def _shellRoot(self) -> tuple[Path, bool]:
        if self.sandbox is None or CURRENT_ACCESS.get() == READ_WRITE:
            return self.workspace, False
        agent = CURRENT_AGENT.get()
        root = await self.sandbox.path(agent)
        if self.logger:
            self.logger.info("shell for '%s' confined to its throwaway copy at %s", agent, root)
        return root, True

    def _auditBefore(self) -> dict | None:
        if self.scope is None or self.scope.allowed is None:
            return None
        return snapshot(self.workspace, self.ignore)

    def _auditAfter(self, before: dict | None) -> str:
        if before is None:
            return ""
        touched = [
            path
            for path in modified(before, snapshot(self.workspace, self.ignore))
            if not self.scope.permits(path)
        ]
        if not touched:
            return ""
        shown = ", ".join(relPath(Path(path), self.workspace) for path in touched)
        if self.logger:
            self.logger.warning("shell changed files outside the verdict scope: %s", shown)
        return (
            f"\n\nWARNING: this command created, deleted or modified files the verdict does not "
            f"allow you to write: {shown}. Undo those changes; only the files the verdict lists "
            "may differ from what was there before."
        )

    async def _git(self, *args: str) -> str:
        if shutil.which(GIT) is None:
            raise MCPError(INVALID_PARAMS, "git is not available")
        try:
            proc = await asyncio.create_subprocess_exec(
                GIT,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(self.workspace),
                start_new_session=True,
            )
        except OSError as exc:
            raise MCPError(INVALID_PARAMS, f"git {args[0]} failed: {exc}") from exc
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=GIT_TIMEOUT)
        except TimeoutError as exc:
            await _terminateGroup(proc)
            raise MCPError(INVALID_PARAMS, f"git {args[0]} timed out") from exc
        return stdout.decode("utf-8", errors="replace").strip()

    async def git_diff(self, staged: bool = False) -> str:
        """Show unstaged diffs in the workspace.

        Use this to see what has changed since the last commit, or to verify
        that a write_file / edit_file produced the expected diff.

        staged: if true, show staged changes instead of unstaged ones.

        Returns the output of 'git diff' (unified diff format). Returns
        "(no changes)" if the workspace is clean.
        """
        args = ["diff", "--no-color"]
        if staged:
            args.append("--staged")
        return await self._git(*args) or "(no changes)"

    async def git_log(self, path: str = "", limit: int = 10) -> str:
        """Show recent commit history for a file or the whole workspace.

        Use this to understand the history of changes to a file.

        path: file relative to the workspace root; if empty, shows workspace history.
        limit: maximum number of commits to show (default 10).

        Returns the output of 'git log --oneline'.
        """
        args = ["log", "--oneline", "--no-color", f"-n{max(1, limit)}"]
        if path:
            args.append(str(resolveSafe(self.workspace, path)))
        return await self._git(*args) or "(no commits)"

    async def git_blame(self, path: str, startLine: int = 0, endLine: int = 0) -> str:
        """Show line-by-line authorship for a file.

        Use this to find who last modified each line and in which commit.

        path: file relative to the workspace root.
        startLine: 1-based first line (0 = from the beginning).
        endLine: 1-based last line (0 = to the end).

        Returns the output of 'git blame' for the selected range.
        """
        target = resolveSafe(self.workspace, path)
        args = ["blame", "--no-color"]
        if startLine > 0:
            args.append(f"-L{startLine},{endLine if endLine > 0 else ''}")
        args.append(str(target))
        return await self._git(*args) or "(no output)"

    async def _overSources(self, path: str, extract: Callable[[SourceParser, str], list[dict]]) -> str:
        target = resolveSafe(self.workspace, path)
        files = await self._offload(self._collectSourceFiles, target)
        out: list[dict] = []
        skipped: list[str] = []

        for file in files:
            try:
                source = await asyncio.to_thread(file.read_text, "utf-8")
            except (OSError, UnicodeDecodeError):
                skipped.append(f"{relPath(file, self.workspace)} (could not read)")
                continue
            if len(source.encode("utf-8")) > self.maxBytes:
                skipped.append(f"{relPath(file, self.workspace)} (too large: {len(source.encode('utf-8'))} > {self.maxBytes})")
                continue
            parser = choose_parser(file.suffix.lower())
            if parser is None:
                skipped.append(f"{relPath(file, self.workspace)} (no parser for {file.suffix or 'this name'})")
                continue
            try:
                found = await asyncio.to_thread(extract, parser, source)
            except SyntaxError:
                skipped.append(f"{relPath(file, self.workspace)} (syntax error)")
                continue
            except Exception as exc:
                raise mapError(exc) from exc
            for entry in found:
                entry["file"] = relPath(file, self.workspace)
                out.append(entry)

        result = formatEntries(out, "(no symbols)")
        if skipped:
            result += "\n\n# Warnings — files skipped:\n" + "\n".join(f"#  {s}" for s in skipped)
        return result

    async def list_symbols(self, path: str = ".") -> str:
        """Outline the classes, functions, methods and variables of source files.

        Use this to understand a file or a package without reading it in full.
        C (.c, .h), Assembly (.s, .S, .asm), Python and PHP sources are parsed;
        other files are ignored.

        path: source file or directory relative to the workspace root; defaults
            to the whole workspace.

        Returns one JSON object per line with "kind" (function, variable, const,
        class, method, the C-only struct, union, enum, typedef, macro,
        prototype, the Assembly-only label, constant, section, global, and the
        PHP-only interface, trait, property, use), "name",
        "line" and "endLine" (1-based, inclusive), "signature", the "docstring"
        if any, and "file" relative to the workspace root. Returns "(no
        symbols)" if nothing is found. Files that could not be parsed are
        listed in a trailing warning.
        """
        return await self._overSources(path, lambda parser, source: parser.listSymbols(source))

    async def find_symbol(self, name: str, path: str = ".") -> str:
        """Locate where a symbol is defined, by exact name.

        Use this to jump straight to a definition instead of searching text.
        C (.c, .h), Assembly (.s, .S, .asm), Python and PHP sources are parsed;
        other files are ignored.

        name: exact symbol name, case sensitive. Give the bare name, without a
            class prefix or parentheses.
        path: source file or directory relative to the workspace root; defaults
            to the whole workspace.

        Returns the same fields as list_symbols, one JSON object per line, for
        every definition matching the name across the searched files. Returns
        "(no symbols)" if the name is not defined anywhere under path.
        """
        if not name:
            raise MCPError(INVALID_PARAMS, "empty name")
        return await self._overSources(path, lambda parser, source: parser.findSymbols(source, name))

    async def get_symbol_body(self, name: str, path: str = ".") -> str:
        """Return the full source text of a class or function, by exact name.

        Prefer this over read_file when you need to inspect one definition in a
        large file. C (.c, .h), Assembly (.s, .S, .asm), Python and PHP
        sources are parsed; other files are ignored. For an Assembly label the
        body runs up to the next non-local label.

        name: exact symbol name, case sensitive.
        path: source file or directory relative to the workspace root; defaults
            to the whole workspace.

        Returns one JSON object per line with "kind", "name", "line" and
        "endLine" (1-based, inclusive), the complete "body" source text, and
        "file" relative to the workspace root. Returns "(no symbols)" if the
        name is not defined anywhere under path.
        """
        if not name:
            raise MCPError(INVALID_PARAMS, "empty name")
        return await self._overSources(path, lambda parser, source: parser.getSymbolBody(source, name))
