"""
Operation envelopes for the unified CMBS Session kernel.

An ``OperationSpec`` is what a caller submits; an ``OperationEnvelope`` is
what the kernel persists after assigning a sequence number, a generated
``op_id`` (when none was provided), timestamps, and an acceptance verdict.

The kernel never interprets ``source_id`` or arbitrary ``payload`` keys
beyond those the active reducer reads — both are opaque-to-the-kernel
provenance the policy attaches for its own use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OperationSpec:
    """Client-submitted operation payload."""

    op_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    source_id: str = ""
    op_id: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True)
class OperationEnvelope:
    """Persisted operation. The op log is a sequence of these."""

    op_id: str
    seq: int
    op_type: str
    payload: dict[str, Any]
    source_id: str
    idempotency_key: str | None
    accepted: bool
    rejected_reason: str | None
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "op_id": self.op_id,
            "seq": self.seq,
            "op_type": self.op_type,
            "payload": dict(self.payload),
            "source_id": self.source_id,
            "idempotency_key": self.idempotency_key,
            "accepted": self.accepted,
            "rejected_reason": self.rejected_reason,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class AppendResult:
    """Return value from ``Session.append``.

    Carries the persisted envelope plus the post-state hash, so callers can
    detect duplicates / rejections / state changes without an extra read.
    """

    envelope: OperationEnvelope
    state_hash_after: str
    survivors_count_after: int
