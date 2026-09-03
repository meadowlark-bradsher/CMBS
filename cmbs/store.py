"""
Persistence SPI for the unified Session kernel.

An ``OpLogStore`` persists ``OperationEnvelope`` records keyed by session
ID. The kernel uses it for crash recovery and for migrating sessions
between processes.

The shipped implementation is in-memory only; external implementations
(file, Redis, Postgres, ...) live outside the package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .operations import OperationEnvelope
from .snapshot import OntologyBundle


@dataclass(frozen=True)
class RecoveredSession:
    """Everything needed to reconstitute a ``Session`` from its store."""

    session_id: str
    initial_hypotheses: frozenset[str]
    ontology: OntologyBundle | None
    stability_window: int
    reducer_version: str
    envelopes: tuple[OperationEnvelope, ...]


@runtime_checkable
class OpLogStore(Protocol):
    """Persistence interface for sessions and their op logs."""

    def create_session(
        self,
        session_id: str,
        initial_hypotheses: frozenset[str],
        ontology: OntologyBundle | None,
        stability_window: int,
        reducer_version: str,
    ) -> None:
        """Register a new session. Raises if the session_id already exists."""

    def append(
        self,
        session_id: str,
        envelope: OperationEnvelope,
    ) -> None:
        """Append an envelope. Envelopes are assumed to arrive in seq order;
        implementations may verify or simply trust."""

    def read_ops(
        self,
        session_id: str,
        from_seq: int | None = None,
        to_seq: int | None = None,
    ) -> tuple[OperationEnvelope, ...]:
        """Return envelopes in seq range (inclusive bounds, 1-indexed)."""

    def head_seq(self, session_id: str) -> int:
        """Return the highest seq in the log (0 if empty)."""

    def recover(self, session_id: str) -> RecoveredSession:
        """Return everything needed to reconstitute the session."""


@dataclass
class _SessionLog:
    session_id: str
    initial_hypotheses: frozenset[str]
    ontology: OntologyBundle | None
    stability_window: int
    reducer_version: str
    envelopes: list[OperationEnvelope] = field(default_factory=list)


class InMemoryOpLogStore:
    """Default in-process implementation of ``OpLogStore``.

    Verifies that envelopes arrive in contiguous seq order; an
    out-of-order append raises rather than corrupting the log.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionLog] = {}

    def create_session(
        self,
        session_id: str,
        initial_hypotheses: frozenset[str],
        ontology: OntologyBundle | None,
        stability_window: int,
        reducer_version: str,
    ) -> None:
        if session_id in self._sessions:
            raise ValueError(f"Session {session_id!r} already exists.")
        self._sessions[session_id] = _SessionLog(
            session_id=session_id,
            initial_hypotheses=frozenset(initial_hypotheses),
            ontology=ontology,
            stability_window=stability_window,
            reducer_version=reducer_version,
        )

    def append(self, session_id: str, envelope: OperationEnvelope) -> None:
        log = self._require(session_id)
        expected = len(log.envelopes) + 1
        if envelope.seq != expected:
            raise ValueError(
                f"Out-of-order append for session {session_id!r}: "
                f"got seq {envelope.seq}, expected {expected}."
            )
        log.envelopes.append(envelope)

    def read_ops(
        self,
        session_id: str,
        from_seq: int | None = None,
        to_seq: int | None = None,
    ) -> tuple[OperationEnvelope, ...]:
        log = self._require(session_id)
        head = len(log.envelopes)
        lo = 1 if from_seq is None else from_seq
        hi = head if to_seq is None else to_seq
        if lo < 1:
            raise ValueError(f"from_seq must be >= 1, got {lo}.")
        if hi < lo - 1:
            raise ValueError(f"to_seq ({hi}) must not precede from_seq ({lo}).")
        return tuple(log.envelopes[lo - 1 : hi])

    def head_seq(self, session_id: str) -> int:
        return len(self._require(session_id).envelopes)

    def recover(self, session_id: str) -> RecoveredSession:
        log = self._require(session_id)
        return RecoveredSession(
            session_id=log.session_id,
            initial_hypotheses=log.initial_hypotheses,
            ontology=log.ontology,
            stability_window=log.stability_window,
            reducer_version=log.reducer_version,
            envelopes=tuple(log.envelopes),
        )

    def session_ids(self) -> tuple[str, ...]:
        """IDs of every session this store knows about, in creation order."""
        return tuple(self._sessions)

    def _require(self, session_id: str) -> _SessionLog:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise KeyError(f"Unknown session_id {session_id!r}.") from None
