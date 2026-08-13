from enum import Enum

from pydantic import BaseModel


class Status(str, Enum):
    CONCLUDED = "concluded"
    NEEDS_PEER = "needs_peer"


class Stance(str, Enum):
    PROPOSER = "proposer"
    OPPONENT = "opponent"


class Finding(BaseModel):
    file: str
    lines: list[int] = []
    summary: str


class Objection(BaseModel):
    claim: str
    evidence: str = ""


class Resolution(BaseModel):
    objection_id: str
    how: str


class Proposal(BaseModel):
    solution: str
    resolves: list[Resolution] = []
    findings: list[Finding] = []
    status: Status
    confidence: float


class Rebuttal(BaseModel):
    objections: list[Objection] = []
    accepts: bool
    findings: list[Finding] = []
    status: Status
    confidence: float


class TrackedObjection(BaseModel):
    id: str
    exchange: int
    agent: str
    claim: str
    evidence: str = ""
    resolved_by: str | None = None


class Turn(BaseModel):
    exchange: int
    agent: str
    stance: Stance
    proposal: Proposal | None = None
    rebuttal: Rebuttal | None = None
    failed: str | None = None


class Escalation(BaseModel):
    question: str
    consensus: bool
    transcript: str
    open_objections: list[TrackedObjection] = []
    findings: list[Finding] = []


class Verdict(BaseModel):
    verdict: str
    rationale: str
    allowed_files: list[str]


class WorkerReport(BaseModel):
    status: str
    changed_files: list[str] = []
    summary: str


class Review(BaseModel):
    approved: bool
    note: str
