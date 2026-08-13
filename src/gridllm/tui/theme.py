from textual.design import ColorSystem

PALETTE = ColorSystem(
    primary="#7aa2f7",
    secondary="#9ece6a",
    background="#1a1b26",
    surface="#24283b",
    panel="#1f2335",
    foreground="#c0caf5",
    warning="#e0af68",
    error="#f7768e",
    success="#9ece6a",
    accent="#bb9af7",
)

ROLE_COLORS = {
    "worker": "#7aa2f7",
    "thinker-1": "#9ece6a",
    "thinker-2": "#bb9af7",
    "judge": "#e0af68",
}

KIND_ICONS = {
    "llm.call": "→",
    "llm.response": "←",
    "llm.thinking": "…",
    "tool.call": "▣",
    "tool.result": "▣",
    "debate.round": "◐",
    "debate.done": "●",
    "escalation": "▲",
    "verdict": "★",
    "execution.start": "▷",
    "execution.done": "■",
    "run.done": "✓",
    "log": "·",
    "finding": "◉",
    "error": "✗",
    "token.usage": "₮",
}