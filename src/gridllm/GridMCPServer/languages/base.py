from abc import ABC, abstractmethod


class SourceParser(ABC):

    @abstractmethod
    def listSymbols(self, sourceText: str) -> list[dict]:
        ...

    def findSymbols(self, sourceText: str, symbolName: str) -> list[dict]:
        return [s for s in self.listSymbols(sourceText) if s["name"] == symbolName]

    def getSymbolBody(self, sourceText: str, symbolName: str) -> list[dict]:
        lines = sourceText.splitlines()
        results: list[dict] = []
        for symbol in self.findSymbols(sourceText, symbolName):
            start = symbol["line"]
            end = symbol["endLine"]
            if start <= 0 or end < start:
                continue
            results.append({
                "kind": symbol["kind"],
                "name": symbol["name"],
                "line": start,
                "endLine": end,
                "body": "\n".join(lines[start - 1:end]),
            })
        return results
