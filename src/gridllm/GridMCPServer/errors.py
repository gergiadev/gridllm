from mcp import MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS


def mapError(exc: Exception) -> MCPError:
    if isinstance(exc, MCPError):
        return exc
    if isinstance(exc, FileNotFoundError):
        return MCPError(INVALID_PARAMS, f"file not found: {exc.filename or exc}")
    if isinstance(exc, IsADirectoryError):
        return MCPError(INVALID_PARAMS, f"is a directory, not a file: {exc.filename or exc}")
    if isinstance(exc, UnicodeDecodeError):
        return MCPError(INVALID_PARAMS, f"file is not valid UTF-8 text: {exc}")
    if isinstance(exc, NotADirectoryError):
        return MCPError(INVALID_PARAMS, f"not a directory: {exc}")
    if isinstance(exc, PermissionError):
        return MCPError(INTERNAL_ERROR, f"permission denied: {exc}")
    return MCPError(INTERNAL_ERROR, f"internal error: {exc}")
