"""
Operation envelopes for the unified CMBS Session kernel.

An ``OperationSpec`` is what a caller submits; an ``OperationEnvelope`` is
what the kernel persists after assigning a sequence number, a generated
``op_id`` (when none was provided), timestamps, and an acceptance verdict.

The kernel never interprets ``source_id`` or arbitrary ``payload`` keys
beyond those the active reducer reads — both are opaque-to-the-kernel
provenance the policy attaches for its own use.

Every envelope also carries a chained ``log_hash`` (scheme
:data:`LOG_HASH_SCHEME`): the SHA-256 of the previous envelope's hash
followed by this envelope's canonical bytes. ``Session.append`` computes it;
``Session.recover`` verifies the chain. See :func:`compute_log_hash`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

LOG_HASH_SCHEME = "log_hash_v1"
"""Identifier of the canonicalization and chaining scheme below. Stored
with the session by ``OpLogStore.create_session`` and returned in
``RecoveredSession.log_hash_scheme``; recovery refuses a log written under
a scheme it does not know."""

LOG_HASH_GENESIS = "cmbs:log_hash_v1:genesis"
"""The link that precedes the first envelope of a chain."""


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
    log_hash: str | None = None
    """Chained hash of this envelope; see :func:`compute_log_hash`. ``None``
    on envelopes persisted before the chain existed (legacy logs) and on
    envelopes a caller constructs by hand."""

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
            "log_hash": self.log_hash,
        }


# ----------------------------------------------------------------------
# Log hash chain (scheme ``log_hash_v1``)
# ----------------------------------------------------------------------


def canonical_envelope_bytes(envelope: OperationEnvelope) -> bytes:
    """Pinned canonical form of an envelope, excluding its hash fields.

    Every field of :class:`OperationEnvelope` except ``log_hash`` is
    serialized as JSON with sorted keys, compact separators, and
    ``ensure_ascii=False``, then UTF-8 encoded. Containers inside
    ``payload`` are normalized first: dict keys become strings and are
    sorted, sets become sorted lists, tuples become lists. Floats use
    Python's shortest round-trip ``repr`` (the ``json`` default, stable
    since Python 3.1), so ``created_at`` canonicalizes the same way on
    every replay. Bools stay bools, ints stay ints.

    ``created_at`` is wall-clock time taken once, at append; it is stored
    on the record and never regenerated, so chaining over it is
    replay-deterministic: recomputing the chain from the persisted
    envelopes reproduces it exactly.

    Raises ``TypeError`` if the payload holds a value JSON cannot
    represent; a durable store would have refused it anyway.
    """
    content = {
        "op_id": envelope.op_id,
        "seq": envelope.seq,
        "op_type": envelope.op_type,
        "payload": _canonical_value(envelope.payload),
        "source_id": envelope.source_id,
        "idempotency_key": envelope.idempotency_key,
        "accepted": envelope.accepted,
        "rejected_reason": envelope.rejected_reason,
        "created_at": envelope.created_at,
    }
    text = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


def compute_log_hash(previous: str | None, envelope: OperationEnvelope) -> str:
    """``sha256(previous || canonical(envelope))`` as a hex digest.

    ``previous`` is the ``log_hash`` of the envelope at ``seq - 1``, or
    ``None`` (meaning :data:`LOG_HASH_GENESIS`) for the first envelope of a
    chain. The envelope's own ``log_hash`` is not an input, so the result
    is the same whether or not it has been filled in.

    Because each link covers the one before it, editing any field of any
    envelope changes its hash and every later hash; a log is tamper-evident
    from the first hashed envelope onward.
    """
    link = LOG_HASH_GENESIS if previous is None else previous
    digest = hashlib.sha256()
    digest.update(link.encode("utf-8"))
    digest.update(canonical_envelope_bytes(envelope))
    return digest.hexdigest()


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): _canonical_value(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, list | tuple):
        return [_canonical_value(v) for v in value]
    if isinstance(value, set | frozenset):
        return sorted(_canonical_value(v) for v in value)
    return value


@dataclass(frozen=True)
class AppendResult:
    """Return value from ``Session.append``.

    Carries the persisted envelope plus the post-state hash, so callers can
    detect duplicates / rejections / state changes without an extra read.
    """

    envelope: OperationEnvelope
    state_hash_after: str
    survivors_count_after: int
