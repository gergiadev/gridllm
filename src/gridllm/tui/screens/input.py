from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Label, TextArea


class TaskInputScreen(Screen):
    BINDINGS = [  # noqa: RUF012 - Textual idiom
        Binding("enter", "submit", "Submit"),
        Binding("escape", "app.quit", "Quit"),
    ]

    DEFAULT_CSS = """
    TaskInputScreen {
        align: center middle;
    }
    TaskInputScreen > Vertical {
        width: 80%;
        height: auto;
        padding: 1 2;
        border: round $primary;
    }
    TaskInputScreen Label#title {
        text-align: center;
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    TaskInputScreen TextArea#task {
        height: 10;
        margin-bottom: 1;
    }
    TaskInputScreen Button#go {
        align-horizontal: center;
    }
    """

    def __init__(self, initial_task: str = "") -> None:
        super().__init__()
        self.initial_task = initial_task

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("gridllm — insert task", id="title")
            yield TextArea(self.initial_task, id="task")
            yield Button("Run [Enter]", id="go", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "go":
            self._submit()

    def action_submit(self) -> None:
        self._submit()

    def _submit(self) -> None:
        text = self.query_one("#task", TextArea).text.strip()
        if text:
            self.dismiss(text)