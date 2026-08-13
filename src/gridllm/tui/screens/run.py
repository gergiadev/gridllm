from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Label, RichLog

from ... import VERSION
from ...events import (
    KIND_DEBATE_DONE,
    KIND_DEBATE_ROUND,
    KIND_ERROR,
    KIND_ESCALATION,
    KIND_EXECUTION_DONE,
    KIND_EXECUTION_START,
    KIND_FINDING,
    KIND_LLM_CALL,
    KIND_LLM_RESPONSE,
    KIND_LLM_THINKING,
    KIND_LOG,
    KIND_REVIEW,
    KIND_RUN_DONE,
    KIND_TOKEN_USAGE,
    KIND_TOOL_CALL,
    KIND_TOOL_RESULT,
    KIND_VERDICT,
    Event,
    EventBus,
)
from ...token_counter import AgentTokens, bar
from ..theme import ROLE_COLORS

MUTED = "#565f89"

TITLE = "GridLLM"

ROWS = {
    "main": ("sidebar", "debate", "tools", "findings"),
    "mid": ("verdict", "exec"),
}


class ExecutionScreen(Screen):
    BINDINGS = [  # noqa: RUF012 - Textual idiom
        Binding("ctrl+t", "toggle('tools')", "Tools", show=True),
        Binding("ctrl+d", "toggle('debate')", "Debate", show=True),
        Binding("ctrl+v", "toggle('verdict')", "Verdict", show=True),
        Binding("ctrl+e", "toggle('exec')", "Exec", show=True),
        Binding("ctrl+f", "toggle('findings')", "Findings", show=True),
        Binding("ctrl+l", "toggle('log')", "Log", show=True),
        Binding("ctrl+n", "toggle('tokens')", "Tokens", show=True),
        Binding("ctrl+b", "toggle('sidebar')", "Sidebar", show=True),
        Binding("ctrl+r", "refresh_sidebar", "Refresh", show=True),
        Binding("f1,ctrl+h", "help", "Help", show=True),
        Binding("ctrl+c,ctrl+q,q", "app.quit", "Quit", show=True),
    ]

    DEFAULT_CSS = """
    ExecutionScreen {
        layout: vertical;
    }
    #taskbar {
        height: 1;
        dock: top;
        color: #7aa2f7;
        text-style: bold;
        padding: 0 1;
    }
    #main {
        height: 2fr;
        min-height: 6;
    }
    #mid {
        height: 1fr;
        min-height: 5;
    }
    .panel {
        border: round #1f2335;
        padding: 0 1;
        width: 1fr;
        height: 1fr;
        min-width: 16;
        min-height: 3;
    }
    .panel-title {
        color: #7aa2f7;
        text-style: bold;
        margin-bottom: 0;
    }
    #sidebar { width: 24; display: none; }
    #verdict { display: none; }
    #findings { display: none; }
    #log { height: 1fr; min-height: 5; }
    #tokens { height: 1fr; min-height: 5; display: none; }
    """

    def __init__(self, grid, task: str, bus: EventBus) -> None:
        super().__init__()
        self.grid = grid
        self._grid_task = task
        self.bus = bus
        self._token_agents: dict[str, AgentTokens] = {}
        self._budgets = self._agent_budgets()
        self._grand_total = 0

    def compose(self) -> ComposeResult:
        yield Label(self._taskbar_text(), id="taskbar")
        with Horizontal(id="main"):
            with Vertical(id="sidebar", classes="panel"):
                yield Label("FILES  (CTRL+B)", classes="panel-title")
                yield RichLog(id="sidebar-content", markup=True)
            with Vertical(id="debate", classes="panel"):
                yield Label("DEBATE  (CTRL+D)", classes="panel-title")
                yield RichLog(id="debate-content", markup=True)
            with Vertical(id="tools", classes="panel"):
                yield Label("TOOLS  (CTRL+T)", classes="panel-title")
                yield RichLog(id="tools-content", markup=True)
            with Vertical(id="findings", classes="panel"):
                yield Label("FINDINGS  (CTRL+F)", classes="panel-title")
                yield RichLog(id="findings-content", markup=True)
        with Horizontal(id="mid"):
            with Vertical(id="verdict", classes="panel"):
                yield Label("VERDICT  (CTRL+V)", classes="panel-title")
                yield RichLog(id="verdict-content", markup=True)
            with Vertical(id="exec", classes="panel"):
                yield Label("EXEC  (CTRL+E)", classes="panel-title")
                yield RichLog(id="exec-content", markup=True)
        with Vertical(id="log", classes="panel"):
            yield Label("LOG  (CTRL+L)", classes="panel-title")
            yield RichLog(id="log-content", markup=True)
        with Vertical(id="tokens", classes="panel"):
            yield Label("TOKENS  (CTRL+N)", classes="panel-title")
            yield RichLog(id="tokens-content", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self._sync_rows()
        self._set_status("running")
        self._exec_log().write("[yellow]starting grid...[/]")
        self._pump_task = asyncio.create_task(self._pump_events())
        self._run_task = asyncio.create_task(self._run_grid())

    def on_unmount(self) -> None:
        for task in (getattr(self, "_pump_task", None), getattr(self, "_run_task", None)):
            if task is not None and not task.done():
                task.cancel()

    async def _run_grid(self) -> None:
        try:
            result = await self.grid.run(self._grid_task)
            self._exec_log().write(f"[green]done[/green]\n{result[:1500]}")
            self._set_status("done")
        except Exception as exc:  # noqa: BLE001 - don't kill the TUI on grid errors
            self._exec_log().write(f"[red]grid error:[/red] {exc}")
            self._log_log().write(f"[red]grid error:[/red] {exc}")
            self._set_status("error")

    async def _pump_events(self) -> None:
        async for event in self.bus.subscribe():
            self._dispatch(event)

    def _dispatch(self, event: Event) -> None:
        kind = event.kind
        agent = event.agent or "-"
        agent_col = ROLE_COLORS.get(agent, MUTED)
        agent_tag = f"[{agent_col}]{agent}[/]"
        p = event.payload

        if kind == KIND_DEBATE_ROUND:
            status = p.get("status", "?")
            conf = p.get("confidence", 0)
            note = p.get("note", "")
            exchange = p.get("exchange", 0)
            stance = p.get("stance", "?")
            findings_count = len(p.get("findings", []))
            if p.get("stance") == "proposer":
                tally = f"[+{p.get('resolves', 0)} resolved]"
            else:
                tally = f"[+{p.get('objections', 0)} objection]"
            self._debate_log().write(
                f"{agent_tag} [{stance}] exchange {exchange} conf {conf:.2f} {status} {tally} [+{findings_count} finding]\n  {note[:200]}"
            )
        elif kind == KIND_DEBATE_DONE:
            pending = p.get("open_objections", 0)
            if p.get("consensus"):
                self._debate_log().write(f"[green]consensus[/green] turns={p.get('turns')}")
            else:
                self._debate_log().write(
                    f"[yellow]no consensus[/yellow] turns={p.get('turns')} open objections={pending}"
                )
        elif kind == KIND_ESCALATION:
            outcome = "consensus" if p.get("consensus") else "no consensus"
            self._verdict_log().write(f"[yellow]adjudication[/yellow] ({outcome}) -> {agent_tag}")
        elif kind == KIND_VERDICT:
            allowed = ", ".join(p.get("allowed_files", [])) or "(none)"
            self._verdict_log().write(
                f"* {agent_tag}\n  verdict: {p.get('verdict','')}\n  rationale: {p.get('rationale','')[:300]}\n  writable: {allowed}"
            )
        elif kind == KIND_REVIEW:
            color = "green" if p.get("approved") else "red"
            outcome = "approved" if p.get("approved") else "rejected"
            self._verdict_log().write(f"[{color}]review {outcome}[/{color}] {agent_tag}\n  {p.get('note','')[:300]}")
        elif kind == KIND_ERROR:
            self._log_log().write(f"[red]error[/red] {agent} {p.get('error','')}")
        elif kind == KIND_EXECUTION_START:
            self._exec_log().write(f"[blue]starting[/blue] task: {p.get('task','')[:150]}")
        elif kind == KIND_EXECUTION_DONE:
            self._exec_log().write(f"result:\n{p.get('result','')[:1500]}")
        elif kind == KIND_RUN_DONE:
            self._log_log().write("[green]run done[/green]")
        elif kind == KIND_FINDING:
            lines = p.get("lines", [])
            lines_str = ",".join(str(l) for l in lines) if lines else "?"
            self._findings_log().write(f"* {p.get('file','?')}:{lines_str}\n  {p.get('summary','')[:200]}")
        elif kind == KIND_TOOL_CALL:
            args = p.get("arguments", {})
            self._tools_log().write(f"* {agent_tag} call {p.get('name','?')}\n  args: {str(args)[:200]}")
            self._log_log().write(f"[cyan]tool.call[/cyan] {agent} {p.get('name','?')}")
        elif kind == KIND_TOOL_RESULT:
            err = p.get("error", False)
            color = "red" if err else "green"
            self._tools_log().write(f"[{color}]result {p.get('name','?')}[/{color}]\n  {str(p.get('content',''))[:300]}")
        elif kind == KIND_LLM_CALL:
            self._log_log().write(f"[blue]llm.call[/blue] {agent}")
        elif kind == KIND_LLM_RESPONSE:
            self._log_log().write(f"[green]llm.response[/green] {agent}")
        elif kind == KIND_LLM_THINKING:
            self._log_log().write(f"[magenta]llm.thinking[/magenta] {agent}")
        elif kind == KIND_TOKEN_USAGE:
            self._update_tokens(agent, p)
        elif kind == KIND_LOG:
            self._log_log().write(str(p.get("msg", "")))

    def action_toggle(self, panel_id: str) -> None:
        try:
            widget = self.query_one(f"#{panel_id}")
        except Exception:  # noqa: BLE001 - widget may not be mounted yet
            return
        widget.display = not widget.display
        self._sync_rows()

    def _sync_rows(self) -> None:
        for row, panels in ROWS.items():
            try:
                container = self.query_one(f"#{row}")
            except Exception:  # noqa: BLE001, S112 - widget may not be mounted yet
                continue
            container.display = any(self.query_one(f"#{panel}").display for panel in panels)

    async def action_refresh_sidebar(self) -> None:
        self._sidebar_log().write(f"[{MUTED}]refreshing...[/]")

    def action_help(self) -> None:
        self._log_log().write(
            "keymap: CTRL+T tools, CTRL+D debate, CTRL+V verdict, CTRL+E exec, CTRL+F findings, "
            "CTRL+L log, CTRL+N tokens, CTRL+B sidebar, CTRL+R refresh, CTRL+Q quit"
        )

    def _taskbar_text(self, status: str | None = None) -> str:
        text = f"{TITLE} v{VERSION} (Beta) - Task: {self._grid_task}"
        return f"{text}  {status}" if status else text

    def _set_status(self, status: str) -> None:
        icons = {
            "running": "[yellow]running[/yellow]",
            "done": "[green]done[/green]",
            "error": "[red]error[/red]",
        }
        try:
            self.query_one("#taskbar", Label).update(self._taskbar_text(icons.get(status, status)))
        except Exception:  # noqa: BLE001, S110 - widget may not be mounted yet
            pass

    def _agent_budgets(self) -> dict[str, int]:
        clients = [self.grid.worker, self.grid.judge, *self.grid.thinkers]
        return {client.name: client.params.max_input_tokens for client in clients}

    def _update_tokens(self, agent: str, payload: dict) -> None:
        entry = self._token_agents.setdefault(agent, AgentTokens(budget=self._budgets.get(agent, 0)))
        entry.prompt += int(payload.get("prompt_tokens", 0) or 0)
        entry.completion += int(payload.get("completion_tokens", 0) or 0)
        entry.total += int(payload.get("total_tokens", 0) or 0)
        entry.calls += 1
        self._grand_total += int(payload.get("total_tokens", 0) or 0)
        self._render_tokens()

    def _render_tokens(self) -> None:
        log = self._tokens_log()
        log.clear()
        log.write(
            f"{'agent':<12} {'prompt':>10} {'completion':>12} {'total':>10} {'calls':>6}  {'budget':>10}  bar"
        )
        log.write("-" * 78)
        for agent, entry in self._token_agents.items():
            col = ROLE_COLORS.get(agent, MUTED)
            budget_str = str(entry.budget) if entry.budget else "inf"
            log.write(
                f"[{col}]{agent:<12}[/] {entry.prompt:>10} {entry.completion:>12} "
                f"{entry.total:>10} {entry.calls:>6}  {budget_str:>10}  {bar(entry.used_pct)}"
            )
        log.write("-" * 78)
        log.write(f"[bold]{'TOTAL':<12}[/bold] {'':>10} {'':>12} {self._grand_total:>10} {'':>6}")

    def _debate_log(self) -> RichLog:
        return self.query_one("#debate-content", RichLog)

    def _tools_log(self) -> RichLog:
        return self.query_one("#tools-content", RichLog)

    def _verdict_log(self) -> RichLog:
        return self.query_one("#verdict-content", RichLog)

    def _exec_log(self) -> RichLog:
        return self.query_one("#exec-content", RichLog)

    def _findings_log(self) -> RichLog:
        return self.query_one("#findings-content", RichLog)

    def _log_log(self) -> RichLog:
        return self.query_one("#log-content", RichLog)

    def _tokens_log(self) -> RichLog:
        return self.query_one("#tokens-content", RichLog)

    def _sidebar_log(self) -> RichLog:
        return self.query_one("#sidebar-content", RichLog)