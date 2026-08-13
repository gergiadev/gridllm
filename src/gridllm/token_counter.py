from dataclasses import dataclass

# Dead code (kept for reference, see TUI which tracks tokens directly):
#
# import asyncio
# from dataclasses import field


@dataclass
class AgentTokens:
    prompt: int = 0
    completion: int = 0
    total: int = 0
    calls: int = 0
    budget: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.total)

    @property
    def used_pct(self) -> float:
        if self.budget <= 0:
            return 0.0
        return min(100.0, (self.total / self.budget) * 100.0)


# Dead code (kept for reference, see TUI which tracks tokens directly):
#
# @dataclass
# class TokenSnapshot:
#     per_agent: dict[str, AgentTokens] = field(default_factory=dict)
#     grand_total: int = 0
#     grand_prompt: int = 0
#     grand_completion: int = 0
#     total_calls: int = 0
#
#
# class TokenCounter:
#
#     def __init__(self) -> None:
#         self._agents: dict[str, AgentTokens] = {}
#         self._lock = asyncio.Lock()
#
#     def set_budget(self, agent: str, budget: int) -> None:
#         entry = self._agents.setdefault(agent, AgentTokens())
#         entry.budget = budget
#
#     async def add(self, agent: str, prompt_tokens: int, completion_tokens: int) -> AgentTokens:
#         async with self._lock:
#             entry = self._agents.setdefault(agent, AgentTokens())
#             entry.prompt += prompt_tokens
#             entry.completion += completion_tokens
#             entry.total += prompt_tokens + completion_tokens
#             entry.calls += 1
#             return entry
#
#     def snapshot(self) -> TokenSnapshot:
#         return TokenSnapshot(
#             per_agent=dict(self._agents),
#             grand_total=sum(a.total for a in self._agents.values()),
#             grand_prompt=sum(a.prompt for a in self._agents.values()),
#             grand_completion=sum(a.completion for a in self._agents.values()),
#             total_calls=sum(a.calls for a in self._agents.values()),
#         )


def bar(used_pct: float, width: int = 12) -> str:
    filled = round(used_pct / 100.0 * width)
    filled = max(0, min(width, filled))
    return "[" + "█" * filled + "░" * (width - filled) + f"] {used_pct:5.1f}%"