import pytest
from pydantic import ValidationError

from gridllm import debate
from gridllm.messages import (
    Objection,
    Proposal,
    Rebuttal,
    Resolution,
    Stance,
    Status,
    Turn,
)

HOW = "The bound is checked at vm.c:42 before the write, so the index cannot exceed the stack."


def proposal(solution: str = "fix it", confidence: float = 0.9, status: Status = Status.CONCLUDED) -> Proposal:
    return Proposal(solution=solution, status=status, confidence=confidence)


def acceptance() -> Rebuttal:
    return Rebuttal(accepts=True, status=Status.CONCLUDED, confidence=0.9)


@pytest.fixture
def ledger() -> debate.ObjectionLedger:
    ledger = debate.ObjectionLedger()
    ledger.open(0, "thinker-2", [Objection(claim="off by one", evidence="vm.c:42")])
    return ledger


def test_objections_get_an_id_from_exchange_agent_and_index(ledger):
    assert [entry.id for entry in ledger.pending()] == ["0-thinker-2-0"]


def test_another_agent_closes_an_objection_with_a_substantive_answer(ledger):
    assert ledger.resolve("thinker-1", [Resolution(objection_id="0-thinker-2-0", how=HOW)]) == ([], [], [])
    assert ledger.pending() == []


@pytest.mark.parametrize("how", ["done", "Cannot resolve this one without running the binary."])
def test_a_trivial_resolution_leaves_the_objection_open(ledger, how):
    _, rejected, _ = ledger.resolve("thinker-1", [Resolution(objection_id="0-thinker-2-0", how=how)])
    assert rejected == ["0-thinker-2-0"]
    assert len(ledger.pending()) == 1


def test_an_unknown_id_is_reported(ledger):
    unknown, _, _ = ledger.resolve("thinker-1", [Resolution(objection_id="9-nobody-0", how=HOW)])
    assert unknown == ["9-nobody-0"]


def test_an_own_objection_closes_only_once_confirmed(ledger):
    _, _, own = ledger.resolve("thinker-2", [Resolution(objection_id="0-thinker-2-0", how=HOW)])
    assert own == ["0-thinker-2-0"]
    assert len(ledger.pending()) == 1
    assert ledger.confirm("thinker-2") == ["0-thinker-2-0"]
    assert ledger.pending() == []


def test_consensus_needs_a_confident_conclusion_and_every_opponent(ledger):
    assert debate.consensus(proposal(), [acceptance()], [], 0.8)
    assert not debate.consensus(proposal(confidence=0.5), [acceptance()], [], 0.8)
    assert not debate.consensus(proposal(status=Status.NEEDS_PEER), [acceptance()], [], 0.8)
    assert not debate.consensus(proposal(), [acceptance(), None], [], 0.8)
    assert not debate.consensus(proposal(), [], [], 0.8)
    assert not debate.consensus(proposal(), [acceptance()], ledger.pending(), 0.8)


def test_only_the_latest_proposal_is_rendered_in_full():
    old = "old " * 400
    new = "new " * 400
    history = [
        Turn(exchange=0, agent="thinker-1", stance=Stance.PROPOSER, proposal=proposal(old)),
        Turn(exchange=1, agent="thinker-2", stance=Stance.PROPOSER, proposal=proposal(new)),
    ]
    rendered = debate.transcript(history, debate.ObjectionLedger())
    assert new in rendered
    assert old not in rendered
    assert "[...]" in rendered


@pytest.mark.parametrize("confidence", [85, -0.1])
def test_confidence_outside_the_unit_interval_is_refused(confidence):
    with pytest.raises(ValidationError):
        proposal(confidence=confidence)
