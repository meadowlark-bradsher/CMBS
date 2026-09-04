"""
Legacy replay shim for CMBS.

This adapter exists solely to preserve audit/replay continuity for legacy
logs. It accepts legacy IDs as opaque strings and forwards elimination
events into a ``Session`` without validation or interpretation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from cmbs.session import Session
from cmbs.snapshot import ProbeResult


@dataclass(frozen=True)
class LegacyEliminationEvent:
    """Legacy elimination event with opaque identifiers."""

    probe_id: str
    observable_id: str
    eliminated_hypotheses: set[str]


class LegacyReplayAdapter:
    """
    Thin adapter for replaying legacy elimination events.

    Responsibilities:
    - Accept legacy IDs as opaque strings
    - Translate elimination events into ``Session.submit_probe_result``
    - Perform no validation or interpretation
    """

    def __init__(self, session: Session, *, source_id: str = "adapter://legacy") -> None:
        self._session = session
        self._source_id = source_id

    @property
    def session(self) -> Session:
        """Access the underlying session."""
        return self._session

    def submit_elimination_event(self, event: LegacyEliminationEvent) -> ProbeResult:
        """Submit a single legacy elimination event to CMBS."""
        return self._session.submit_probe_result(
            probe_id=event.probe_id,
            observable_id=event.observable_id,
            eliminated=set(event.eliminated_hypotheses),
            source_id=self._source_id,
        )

    def submit_elimination_events(
        self,
        events: Iterable[LegacyEliminationEvent],
    ) -> list[ProbeResult]:
        """Submit multiple legacy elimination events in order."""
        return [self.submit_elimination_event(event) for event in events]


def submit_legacy_elimination(
    session: Session,
    probe_id: str,
    observable_id: str,
    eliminated_hypotheses: Iterable[str],
    *,
    source_id: str = "adapter://legacy",
) -> ProbeResult:
    """
    Convenience function for submitting a single legacy elimination event.
    """
    return session.submit_probe_result(
        probe_id=probe_id,
        observable_id=observable_id,
        eliminated=set(eliminated_hypotheses),
        source_id=source_id,
    )
