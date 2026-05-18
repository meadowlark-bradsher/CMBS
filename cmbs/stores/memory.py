"""
In-memory elimination store.
"""

from __future__ import annotations

from ..spi.elimination_store import (
    EliminationProvenance,
    EliminationResult,
    RecoveredState,
)


class InMemoryStore:
    def __init__(self) -> None:
        self._universes: dict[str, frozenset[str]] = {}
        self._tombstones: dict[str, set[str]] = {}

    def create_session(self, session_id: str, hypothesis_ids: frozenset[str]) -> None:
        if session_id in self._universes:
            raise ValueError(f"Session '{session_id}' already exists.")
        self._universes[session_id] = frozenset(hypothesis_ids)
        self._tombstones[session_id] = set()

    def eliminate(
        self,
        session_id: str,
        eliminated: set[str],
        provenance: EliminationProvenance,
    ) -> EliminationResult:
        self._require_session(session_id)
        survivors = self._universes[session_id] - self._tombstones[session_id]
        applied = eliminated & survivors
        already = eliminated - applied
        self._tombstones[session_id] |= applied
        return EliminationResult(
            applied=frozenset(applied),
            already_eliminated=frozenset(already),
        )

    def get_survivors(self, session_id: str) -> frozenset[str]:
        self._require_session(session_id)
        return frozenset(
            self._universes[session_id] - self._tombstones[session_id]
        )

    def get_eliminated(self, session_id: str) -> frozenset[str]:
        self._require_session(session_id)
        return frozenset(self._tombstones[session_id])

    def recover(self, session_id: str) -> RecoveredState:
        self._require_session(session_id)
        return RecoveredState(
            hypothesis_ids=self._universes[session_id],
            eliminated=frozenset(self._tombstones[session_id]),
            survivors=self.get_survivors(session_id),
        )

    def _require_session(self, session_id: str) -> None:
        if session_id not in self._universes:
            raise KeyError(f"Unknown session_id '{session_id}'.")
