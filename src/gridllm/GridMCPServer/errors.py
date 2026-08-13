from mcp import MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS, METHOD_NOT_FOUND


def mapError(exc: Exception) -> MCPError:
    if isinstance(exc, MCPError):
        return exc
    if isinstance(exc, FileNotFoundError):
        return MCPError(METHOD_NOT_FOUND, f"file not found: {exc.filename or exc}")
    if isinstance(exc, NotADirectoryError):
        return MCPError(INVALID_PARAMS, f"not a directory: {exc}")
    if isinstance(exc, PermissionError):
        return MCPError(INTERNAL_ERROR, f"permission denied: {exc}")
    return MCPError(INTERNAL_ERROR, f"internal error: {exc}")
