"""Models for CMBS v2 operator-log sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OperationSpec:
    """Client-submitted operation payload."""

    op_id: str | None
    op_type: str
    payload: dict[str, Any]
    source_id: str
    preconditions: list[str] = field(default_factory=list)
    commutativity_key: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True)
class OperationEnvelope:
    """Append-only operation envelope persisted in a branch log."""

    op_id: str
    seq: int
    branch_id: str
    origin_seq: int
    op_type: str
    payload: dict[str, Any]
    source_id: str
    preconditions: list[str]
    commutativity_key: str | None
    idempotency_key: str | None
    accepted: bool
    rejected_reason: str | None
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "op_id": self.op_id,
            "seq": self.seq,
            "branch_id": self.branch_id,
            "origin_seq": self.origin_seq,
            "type": self.op_type,
            "payload": self.payload,
            "source_id": self.source_id,
            "preconditions": list(self.preconditions),
            "commutativity_key": self.commutativity_key,
            "idempotency_key": self.idempotency_key,
            "accepted": self.accepted,
            "rejected_reason": self.rejected_reason,
            "created_at": self.created_at,
        }


@dataclass
class BranchRecord:
    """Mutable branch state for a session."""

    branch_id: str
    from_branch: str | None
    from_seq: int
    note: str | None
    created_at: float
    op_log: list[OperationEnvelope] = field(default_factory=list)
    idempotency_index: dict[str, OperationEnvelope] = field(default_factory=dict)

    @property
    def head_seq(self) -> int:
        return len(self.op_log)


@dataclass
class SessionRecord:
    """Top-level v2 session state."""

    sid: str
    ontology: dict[str, Any]
    initial_hypotheses: list[str]
    default_reducer: str
    metadata: dict[str, Any]
    created_at: float
    branches: dict[str, BranchRecord] = field(default_factory=dict)
