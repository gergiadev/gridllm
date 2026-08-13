from __future__ import annotations

from textual.app import App
from textual.binding import Binding

from .. import VERSION
from ..events import EventBus
from .screens.run import ExecutionScreen


class GridApp(App):
    TITLE = "GridLLM"
    SUB_TITLE = f"v{VERSION} (Beta)"

    BINDINGS = [  # noqa: RUF012 - Textual idiom
        Binding("ctrl+c,ctrl+q,q", "quit", "Quit", show=True),
    ]

    def __init__(self, grid, task: str, bus: EventBus) -> None:
        super().__init__()
        self.grid = grid
        self._grid_task = task
        self.bus = bus

    def on_mount(self) -> None:
        self.push_screen(ExecutionScreen(self.grid, self._grid_task, self.bus))