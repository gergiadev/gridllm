import asyncio
import json
from pathlib import Path

from . import debate, paths
from .config import DebateConfig
from .events import (
    KIND_DEBATE_DONE,
    KIND_DEBATE_ROUND,
    KIND_ERROR,
    KIND_ESCALATION,
    KIND_EXECUTION_DONE,
    KIND_EXECUTION_START,
    KIND_FINDING,
    KIND_LOG,
    KIND_REVIEW,
    KIND_RUN_DONE,
    KIND_VERDICT,
    EventBus,
)
from .LLMClient import AgentError, LLMClient
from .messages import (
    Escalation,
    Review,
    Stance,
    Turn,
    Verdict,
    WorkerReport,
)

REVIEW_BRIEF = (
    "The verdict below has already been carried out by the worker. Your access is read-only.\n"
    "Re-read the files that were changed and decide whether the verdict was applied correctly and completely.\n"
    "Set \"approved\" to true only if what is on disk matches the verdict; otherwise set it to false and say in "
    "\"note\" exactly what is wrong or missing."
)


def _norm(path: str) -> str:
    return Path(path).as_posix().removeprefix("./")


class Grid:

    def __init__(
        self,
        worker: LLMClient,
        thinkers: list[LLMClient],
        judge: LLMClient,
        settings: DebateConfig | None = None,
        bus: EventBus | None = None,
        scope=None,
    ):
        self.worker = worker
        self.thinkers = thinkers
        self.judge = judge
        self.settings = settings or DebateConfig()
        self.bus = bus
        self.scope = scope
        self.transcript_path = paths.run_path()
        self._seen_findings: set[tuple] = set()

    async def run(self, task: str) -> str:
        EventBus.emit_to(self.bus, KIND_EXECUTION_START, {"task": task})
        EventBus.emit_to(self.bus, KIND_LOG, {"msg": f"transcript: {self.transcript_path}"})

        history, ledger, agreed = await self._debate(task)
        EventBus.emit_to(
            self.bus,
            KIND_DEBATE_DONE,
            {"consensus": agreed, "turns": len(history), "open_objections": len(ledger.pending())},
        )

        verdict = await self._adjudicate(task, history, ledger, agreed)
        result = await self._execute(task, verdict)
        EventBus.emit_to(self.bus, KIND_EXECUTION_DONE, {"result": result[:2000]})
        EventBus.emit_to(self.bus, KIND_RUN_DONE, {"result": result[:2000]})
        return result

    async def _debate(self, task: str) -> tuple[list[Turn], debate.ObjectionLedger, bool]:
        history: list[Turn] = []
        ledger = debate.ObjectionLedger()

        for exchange in range(self.settings.max_exchanges):
            proposer = self.thinkers[exchange % len(self.thinkers)]
            opponents = [thinker for thinker in self.thinkers if thinker is not proposer]

            proposal = await self._turn(proposer, Stance.PROPOSER, task, history, ledger, exchange)
            history.append(proposal)
            self._persist(task, history, ledger)

            if proposal.proposal is None:
                continue

            unknown, rejected, self_resolved = ledger.resolve(proposer.name, proposal.proposal.resolves)
            if unknown:
                self._report(proposer.name, f"unknown objection ids in resolves: {', '.join(unknown)}")
            if rejected:
                self._report(
                    proposer.name,
                    f"trivial resolutions rejected — objections stay open: {', '.join(rejected)}",
                )
            if self_resolved:
                self._report(
                    proposer.name,
                    f"resolved own objections filed as opponent "
                    f"(will be confirmed by other thinkers): {', '.join(self_resolved)}",
                )

            snapshot = list(history)
            rebuttals = await asyncio.gather(
                *[self._turn(o, Stance.OPPONENT, task, snapshot, ledger, exchange) for o in opponents]
            )
            history.extend(rebuttals)

            for turn in rebuttals:
                if turn.rebuttal is not None:
                    ledger.open(exchange, turn.agent, turn.rebuttal.objections)

            self._persist(task, history, ledger)

            if exchange + 1 < self.settings.min_exchanges:
                continue

            if debate.consensus(
                proposal.proposal,
                [turn.rebuttal for turn in rebuttals],
                ledger.pending(),
                self.settings.confidence_threshold,
            ):
                return history, ledger, True

        if not any(turn.proposal is not None for turn in history):
            raise RuntimeError(f"no thinker produced a proposal, transcript at {self.transcript_path}")

        return history, ledger, False

    async def _turn(
        self,
        thinker: LLMClient,
        stance: Stance,
        task: str,
        history: list[Turn],
        ledger: debate.ObjectionLedger,
        exchange: int,
    ) -> Turn:
        try:
            answer = await thinker.ask(debate.prompt(task, stance, history, ledger), debate.schema(stance))
        except AgentError as error:
            self._report(thinker.name, f"turn failed at exchange {exchange}: {error}")
            return Turn(exchange=exchange, agent=thinker.name, stance=stance, failed=str(error))

        turn = Turn(
            exchange=exchange,
            agent=thinker.name,
            stance=stance,
            proposal=answer if stance is Stance.PROPOSER else None,
            rebuttal=answer if stance is Stance.OPPONENT else None,
        )
        self._announce(turn)
        return turn

    def _announce(self, turn: Turn) -> None:
        source = turn.proposal or turn.rebuttal
        if source is None:
            return

        if turn.proposal is not None:
            note = turn.proposal.solution
            counts = {"resolves": len(turn.proposal.resolves), "objections": 0}
        else:
            note = "; ".join(objection.claim for objection in turn.rebuttal.objections) or "accepts the proposal"
            counts = {"resolves": 0, "objections": len(turn.rebuttal.objections)}

        EventBus.emit_to(
            self.bus,
            KIND_DEBATE_ROUND,
            {
                "exchange": turn.exchange,
                "agent": turn.agent,
                "stance": turn.stance.value,
                "status": source.status.value,
                "confidence": source.confidence,
                "note": note,
                "findings": [finding.model_dump() for finding in source.findings],
                **counts,
            },
            turn.agent,
        )

        for finding in source.findings:
            key = (finding.file, tuple(finding.lines), finding.summary)
            if key in self._seen_findings:
                continue
            self._seen_findings.add(key)
            EventBus.emit_to(
                self.bus,
                KIND_FINDING,
                {
                    "agent": turn.agent,
                    "file": finding.file,
                    "lines": finding.lines,
                    "summary": finding.summary,
                },
                turn.agent,
            )

    def _report(self, agent: str | None, message: str) -> None:
        EventBus.emit_to(self.bus, KIND_ERROR, {"error": message}, agent)

    def _persist(self, task: str, history: list[Turn], ledger: debate.ObjectionLedger) -> None:
        payload = {
            "task": task,
            "turns": [turn.model_dump(mode="json") for turn in history],
            "objections": [entry.model_dump(mode="json") for entry in ledger.entries],
        }
        try:
            self.transcript_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as error:
            self._report(None, f"could not save the transcript: {error}")

    async def _adjudicate(
        self,
        task: str,
        history: list[Turn],
        ledger: debate.ObjectionLedger,
        agreed: bool,
    ) -> Verdict:
        escalation = Escalation(
            question=task,
            consensus=agreed,
            transcript=debate.transcript(history, ledger),
            open_objections=ledger.pending(),
            findings=debate.merge_findings(history),
        )
        EventBus.emit_to(
            self.bus,
            KIND_ESCALATION,
            {"question": task, "turns": len(history), "consensus": agreed},
            self.judge.name,
        )

        try:
            verdict = await self.judge.ask(escalation.model_dump_json(indent=2), Verdict)
        except AgentError as error:
            raise RuntimeError(f"{error}, debate transcript at {self.transcript_path}") from error

        EventBus.emit_to(
            self.bus,
            KIND_VERDICT,
            {
                "verdict": verdict.verdict,
                "rationale": verdict.rationale,
                "allowed_files": verdict.allowed_files,
            },
            self.judge.name,
        )
        return verdict

    async def _execute(self, task: str, verdict: Verdict) -> str:
        if not verdict.allowed_files:
            self._report(self.judge.name, "the verdict allows no file to be written")

        self.worker.toolbox.touched.clear()
        if self.scope is not None:
            self.scope.allow(verdict.allowed_files)

        try:
            report = await self.worker.ask(
                f"{task}\n\nConclusion to apply:\n{verdict.verdict}\n\n"
                f"You may only write these files:\n{', '.join(verdict.allowed_files) or '(none)'}",
                WorkerReport,
            )
        finally:
            if self.scope is not None:
                self.scope.clear()

        touched = {_norm(path) for path in self.worker.toolbox.touched}
        declared = {_norm(path) for path in report.changed_files}
        if declared != touched:
            self._report(
                self.worker.name,
                f"declared changes {sorted(declared) or '[]'} do not match the files actually written "
                f"{sorted(touched) or '[]'}",
            )

        review = await self._review(verdict, report, touched)

        lines = [report.summary, f"status: {report.status}", f"changed: {', '.join(sorted(touched)) or '(none)'}"]
        if review is not None:
            outcome = "approved" if review.approved else "rejected"
            lines.append(f"review: {outcome} - {review.note}")
        return "\n".join(lines)

    async def _review(self, verdict: Verdict, report: WorkerReport, touched: set[str]) -> Review | None:
        if not self.settings.verify_execution:
            return None

        prompt = (
            f"{REVIEW_BRIEF}\n\nVerdict:\n{verdict.verdict}\n\n"
            f"What the worker reports:\n{report.summary}\n\n"
            f"Files written:\n{', '.join(sorted(touched)) or '(none)'}"
        )
        try:
            review = await self.judge.ask(prompt, Review)
        except AgentError as error:
            self._report(self.judge.name, f"review failed: {error}")
            return None

        EventBus.emit_to(
            self.bus,
            KIND_REVIEW,
            {"approved": review.approved, "note": review.note},
            self.judge.name,
        )
        return review
