"""
Persistence SPI for the unified Session kernel.

An ``OpLogStore`` persists ``OperationEnvelope`` records keyed by session
ID. The kernel uses it for crash recovery and for migrating sessions
between processes.

The shipped implementation is in-memory only; external implementations
(file, Redis, Postgres, ...) live outside the package.
"""

from __future__ import annotations

from dataclasses import dataclass
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


class InMemoryOpLogStore:
    """Default in-process implementation of ``OpLogStore``."""

    def __init__(self) -> None:
        raise NotImplementedError("InMemoryOpLogStore.__init__")

    def create_session(
        self,
        session_id: str,
        initial_hypotheses: frozenset[str],
        ontology: OntologyBundle | None,
        stability_window: int,
        reducer_version: str,
    ) -> None:
        raise NotImplementedError

    def append(self, session_id: str, envelope: OperationEnvelope) -> None:
        raise NotImplementedError

    def read_ops(
        self,
        session_id: str,
        from_seq: int | None = None,
        to_seq: int | None = None,
    ) -> tuple[OperationEnvelope, ...]:
        raise NotImplementedError

    def head_seq(self, session_id: str) -> int:
        raise NotImplementedError

    def recover(self, session_id: str) -> RecoveredSession:
        raise NotImplementedError
