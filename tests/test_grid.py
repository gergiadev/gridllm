import json
from pathlib import Path

import pytest

from gridllm.config import DebateConfig
from gridllm.events import KIND_ERROR, EventBus
from gridllm.messages import Proposal, Rebuttal, Review, Status, Verdict, WorkerReport
from gridllm.orchestrator import Grid

SOLUTION = "guard the index before the write " * 40


class Scripted:

    def __init__(self, name: str, *answers) -> None:
        self.name = name
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def ask(self, prompt: str, schema=None):
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        return answer() if callable(answer) else answer


def _writes(workspace: Path, files: list[str], declared: list[str]):
    def answer() -> WorkerReport:
        for name in files:
            (workspace / name).write_text("int fixed;\n", encoding="utf-8")
        return WorkerReport(status="done", changed_files=declared, summary="applied")

    return answer


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vm.c").write_text("int broken;\n", encoding="utf-8")
    return tmp_path


def _grid(worker_answer, review: Review, bus: EventBus | None = None) -> Grid:
    proposer = Scripted("thinker-1", Proposal(solution=SOLUTION, status=Status.CONCLUDED, confidence=0.9))
    opponent = Scripted("thinker-2", Rebuttal(accepts=True, status=Status.CONCLUDED, confidence=0.9))
    judge = Scripted("judge", Verdict(verdict="guard it", rationale="agreed", allowed_files=["vm.c"]), review)
    return Grid(
        worker=Scripted("worker", worker_answer),
        thinkers=[proposer, opponent],
        judge=judge,
        settings=DebateConfig(max_exchanges=1, min_exchanges=1),
        bus=bus,
        ignore=(".gridllm",),
    )


async def test_a_run_reports_what_changed_and_the_review(workspace):
    grid = _grid(_writes(workspace, ["vm.c"], ["vm.c"]), Review(approved=True, note="as instructed"))
    result = await grid.run("fix the bug")
    assert "changed: vm.c" in result
    assert "review: approved - as instructed" in result
    assert grid.approved


async def test_opponent_and_judge_read_the_whole_proposal(workspace):
    grid = _grid(_writes(workspace, ["vm.c"], ["vm.c"]), Review(approved=True, note="ok"))
    await grid.run("fix the bug")
    assert SOLUTION in grid.thinkers[1].prompts[0]
    assert SOLUTION in json.loads(grid.judge.prompts[0])["transcript"]


async def test_the_transcript_records_verdict_report_and_review(workspace):
    grid = _grid(_writes(workspace, ["vm.c"], ["vm.c"]), Review(approved=True, note="ok"))
    await grid.run("fix the bug")
    saved = json.loads(grid.transcript_path.read_text(encoding="utf-8"))
    assert saved["verdict"]["allowed_files"] == ["vm.c"]
    assert saved["report"]["status"] == "done"
    assert saved["changed"] == ["vm.c"]
    assert saved["review"]["approved"] is True


async def test_an_undeclared_change_on_disk_is_reported(workspace):
    bus = EventBus()
    grid = _grid(_writes(workspace, ["vm.c", "extra.c"], ["vm.c"]), Review(approved=True, note="ok"), bus)
    result = await grid.run("fix the bug")
    assert "changed: extra.c, vm.c" in result
    errors = [event.payload["error"] for event in bus._history if event.kind == KIND_ERROR]
    assert any("do not match" in error for error in errors)


async def test_a_rejected_review_marks_the_run(workspace):
    grid = _grid(_writes(workspace, [], []), Review(approved=False, note="nothing was written"))
    result = await grid.run("fix the bug")
    assert "review: rejected - nothing was written" in result
    assert not grid.approved
