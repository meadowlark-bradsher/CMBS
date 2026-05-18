"""
SPI interface for elimination persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EliminationProvenance:
    """Opaque provenance attached to an elimination."""

    source_id: str
    trigger: str


@dataclass(frozen=True)
class EliminationResult:
    """Authoritative result of a tombstone merge."""

    applied: frozenset[str]
    already_eliminated: frozenset[str]


@dataclass(frozen=True)
class RecoveredState:
    """Everything CMBS needs to resume a session after restart."""

    hypothesis_ids: frozenset[str]
    eliminated: frozenset[str]
    survivors: frozenset[str]


class EliminationStore(Protocol):
    """SPI for elimination persistence."""

    def create_session(
        self,
        session_id: str,
        hypothesis_ids: frozenset[str],
    ) -> None:
        """Register a new elimination context."""

    def eliminate(
        self,
        session_id: str,
        eliminated: set[str],
        provenance: EliminationProvenance,
    ) -> EliminationResult:
        """Persist tombstones. Idempotent."""

    def get_survivors(self, session_id: str) -> frozenset[str]:
        """Current survivor set (universe minus tombstones)."""

    def get_eliminated(self, session_id: str) -> frozenset[str]:
        """Current tombstone set."""

    def recover(self, session_id: str) -> RecoveredState:
        """Recover full state for a session."""
