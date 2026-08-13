import logging

from .messages import (
    Finding,
    Objection,
    Proposal,
    Rebuttal,
    Resolution,
    Stance,
    Status,
    TrackedObjection,
    Turn,
)

MAX_TEXT_CHARS = 800

TRIVIAL_HOW_PREFIXES = (
    "cannot resolve", "can't resolve", "could not resolve", "couldn't resolve",
    "unable to resolve", "unable to verify", "cannot verify", "can't verify",
    "n/a", "na ", "none", "not possible", "impossible",
    "no way to", "don't know", "do not know", "unsure",
)

MIN_RESOLUTION_LEN = 20

_log = logging.getLogger(__name__)

PROPOSER_BRIEF = (
    "Your stance for this turn is PROPOSER.\n"
    "Put in \"solution\" one complete, concrete answer to the task, grounded in the code you actually read.\n"
    "Every open objection listed below must be answered: add an entry to \"resolves\" with its exact id and how "
    "your proposal deals with it, either by fixing it or by showing why it does not hold. Use the ids as they are "
    "written, never invent one.\n"
    "The \"how\" field must be a substantive explanation — at least two sentences — that references specific "
    "code or evidence. Resolutions that merely state inability (\"cannot resolve\", \"unable to verify\", etc.) "
    "are rejected and the objection stays open.\n"
    "Use status \"concluded\" only when \"resolves\" covers every open objection.\n"
    "Use status \"needs_peer\" while any objection is still unanswered.\n"
    "The confidence field ranges from 0.0 to 1.0 and measures how sure you are that the proposal is correct."
)

OPPONENT_BRIEF = (
    "Your stance for this turn is OPPONENT.\n"
    "Your job is NOT to propose a solution: it is to refute the current proposal.\n"
    "Look for edge cases it breaks on, assumptions it never verified, and statements about the code that are "
    "factually wrong. Read the code to check them instead of guessing.\n"
    "Put every substantive objection in \"objections\", each with its \"claim\" and the \"evidence\" you read to "
    "back it, quoting file and lines.\n"
    "Set \"accepts\" to true, with \"objections\" empty, ONLY when you have no objection left and you accept the "
    "proposal as it stands. It does not mean you are confident in your criticism.\n"
    "Use status \"needs_peer\" while even one objection remains, \"concluded\" otherwise.\n"
    "The confidence field ranges from 0.0 to 1.0 and measures how sure you are of that judgement."
)

BRIEFS = {
    Stance.PROPOSER: PROPOSER_BRIEF,
    Stance.OPPONENT: OPPONENT_BRIEF,
}

SCHEMA_BY_STANCE = {
    Stance.PROPOSER: Proposal,
    Stance.OPPONENT: Rebuttal,
}

NO_TRANSCRIPT = "No debate yet: yours is the opening proposal."
NO_OBJECTIONS = "None: no objection is open right now."


def brief(stance: Stance) -> str:
    return BRIEFS[stance]


def schema(stance: Stance):
    return SCHEMA_BY_STANCE[stance]


def objection_id(exchange: int, agent: str, index: int) -> str:
    return f"{exchange}-{agent}-{index}"


class ObjectionLedger:

    def __init__(self) -> None:
        self.entries: list[TrackedObjection] = []

    def open(self, exchange: int, agent: str, objections: list[Objection]) -> list[TrackedObjection]:
        added = [
            TrackedObjection(
                id=objection_id(exchange, agent, index),
                exchange=exchange,
                agent=agent,
                claim=objection.claim,
                evidence=objection.evidence,
            )
            for index, objection in enumerate(objections)
        ]
        self.entries.extend(added)
        return added

    def resolve(self, agent: str, resolutions: list[Resolution]) -> tuple[list[str], list[str], list[str]]:
        known = {entry.id: entry for entry in self.entries}
        unknown: list[str] = []
        rejected: list[str] = []
        self_resolved: list[str] = []

        for resolution in resolutions:
            entry = known.get(resolution.objection_id)
            if entry is None:
                unknown.append(resolution.objection_id)
                continue
            how = (resolution.how or "").strip()
            how_lower = how.lower()
            if len(how) < MIN_RESOLUTION_LEN:
                rejected.append(resolution.objection_id)
                _log.warning("trivial resolution for %s by %s: too short (%d chars)", resolution.objection_id, agent, len(how))
                continue
            if any(how_lower.startswith(prefix) for prefix in TRIVIAL_HOW_PREFIXES):
                rejected.append(resolution.objection_id)
                _log.warning("trivial resolution for %s by %s: starts with '%s'", resolution.objection_id, agent, how[:60])
                continue
            if entry.agent == agent:
                self_resolved.append(resolution.objection_id)
            entry.resolved_by = agent

        return unknown, rejected, self_resolved

    def pending(self) -> list[TrackedObjection]:
        return [entry for entry in self.entries if entry.resolved_by is None]

    def by_turn(self, exchange: int, agent: str) -> list[TrackedObjection]:
        return [entry for entry in self.entries if entry.exchange == exchange and entry.agent == agent]


def _clip(text: str) -> str:
    text = " ".join((text or "").split())
    if len(text) <= MAX_TEXT_CHARS:
        return text
    return f"{text[:MAX_TEXT_CHARS]}[...]"


def render_objections(entries: list[TrackedObjection]) -> str:
    if not entries:
        return NO_OBJECTIONS
    return "\n".join(f"- [{entry.id}] {_clip(entry.claim)} (evidence: {_clip(entry.evidence)})" for entry in entries)


def _render_findings(findings: list[Finding]) -> list[str]:
    return [
        f"    finding {finding.file}:{','.join(str(line) for line in finding.lines) or '?'} {_clip(finding.summary)}"
        for finding in findings
    ]


def _render_turn(turn: Turn, ledger: ObjectionLedger) -> list[str]:
    head = f"[exchange {turn.exchange}] {turn.agent} as {turn.stance.value}"

    if turn.failed:
        return [f"{head}: TURN FAILED ({_clip(turn.failed)})"]

    if turn.proposal is not None:
        lines = [
            f"{head} status={turn.proposal.status.value} confidence={turn.proposal.confidence:.2f}",
            f"    proposal: {_clip(turn.proposal.solution)}",
        ]
        for resolution in turn.proposal.resolves:
            lines.append(f"    resolves [{resolution.objection_id}]: {_clip(resolution.how)}")
        return lines + _render_findings(turn.proposal.findings)

    if turn.rebuttal is not None:
        verdict = "accepts the proposal" if turn.rebuttal.accepts else "objects"
        lines = [
            f"{head} status={turn.rebuttal.status.value} confidence={turn.rebuttal.confidence:.2f} {verdict}",
        ]
        tracked = ledger.by_turn(turn.exchange, turn.agent)
        for entry in tracked:
            state = "OPEN" if entry.resolved_by is None else f"resolved by {entry.resolved_by}"
            lines.append(f"    objection [{entry.id}] ({state}): {_clip(entry.claim)}")
        return lines + _render_findings(turn.rebuttal.findings)

    return [head]


def transcript(history: list[Turn], ledger: ObjectionLedger) -> str:
    if not history:
        return NO_TRANSCRIPT
    return "\n".join(line for turn in history for line in _render_turn(turn, ledger))


def prompt(task: str, stance: Stance, history: list[Turn], ledger: ObjectionLedger) -> str:
    return (
        f"{task}\n\n{brief(stance)}\n\n"
        f"Open objections:\n{render_objections(ledger.pending())}\n\n"
        f"Debate so far:\n{transcript(history, ledger)}"
    )


def merge_findings(history: list[Turn]) -> list[Finding]:
    merged: dict[tuple, Finding] = {}

    for turn in history:
        source = turn.proposal or turn.rebuttal
        if source is None:
            continue
        for finding in source.findings:
            merged.setdefault((finding.file, tuple(finding.lines), finding.summary), finding)

    return list(merged.values())


def consensus(
    proposal: Proposal | None,
    rebuttals: list[Rebuttal | None],
    pending: list[TrackedObjection],
    threshold: float,
) -> bool:
    if proposal is None or pending:
        return False
    if proposal.status is not Status.CONCLUDED or proposal.confidence < threshold:
        return False
    if not rebuttals:
        return False
    return all(rebuttal is not None and rebuttal.accepts and not rebuttal.objections for rebuttal in rebuttals)
