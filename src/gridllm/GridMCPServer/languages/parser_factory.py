from .base import SourceParser

_registry: dict[str, type[SourceParser]] = {}


def register_parser(*extensions: str):
    def decorate(cls: type[SourceParser]):
        for ext in extensions:
            _registry[ext.lower()] = cls
        return cls
    return decorate


def choose_parser(suffix: str) -> SourceParser | None:
    cls = _registry.get(suffix.lower())
    return cls() if cls else None


def supported_extensions() -> tuple[str, ...]:
    return tuple(sorted(_registry))
