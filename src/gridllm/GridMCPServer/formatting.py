import json


def formatEntry(entry: dict) -> str:
    return json.dumps(entry, ensure_ascii=False)


def formatEntries(entries: list[dict], empty: str) -> str:
    if not entries:
        return empty
    return "\n".join(formatEntry(entry) for entry in entries)
