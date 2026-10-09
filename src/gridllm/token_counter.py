from dataclasses import dataclass


@dataclass
class AgentTokens:
    prompt: int = 0
    completion: int = 0
    total: int = 0
    calls: int = 0
    budget: int = 0
    window: int = 0

    @property
    def used_pct(self) -> float:
        if self.budget <= 0:
            return 0.0
        return min(100.0, (self.window / self.budget) * 100.0)


def bar(used_pct: float, width: int = 12) -> str:
    filled = round(used_pct / 100.0 * width)
    filled = max(0, min(width, filled))
    return "[" + "█" * filled + "░" * (width - filled) + f"] {used_pct:5.1f}%"
