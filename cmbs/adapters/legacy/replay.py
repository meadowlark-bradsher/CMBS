"""
Legacy replay shim for CMBS.

This adapter exists solely to preserve audit/replay continuity for legacy logs.
It accepts legacy IDs as opaque strings and forwards elimination events into
CMBSCore without validation or interpretation.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from cmbs.core import CMBSCore, ProbeResult


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
    - Translate elimination events into CMBSCore.submit_probe_result
    - Perform no validation or interpretation
    """

    def __init__(self, core: CMBSCore) -> None:
        self._core = core

    @property
    def core(self) -> CMBSCore:
        """Access the underlying CMBS core."""
        return self._core

    def submit_elimination_event(self, event: LegacyEliminationEvent) -> ProbeResult:
        """Submit a single legacy elimination event to CMBS."""
        return self._core.submit_probe_result(
            probe_id=event.probe_id,
            observable_id=event.observable_id,
            eliminated=set(event.eliminated_hypotheses),
        )

    def submit_elimination_events(
        self,
        events: Iterable[LegacyEliminationEvent],
    ) -> list[ProbeResult]:
        """Submit multiple legacy elimination events in order."""
        return [self.submit_elimination_event(event) for event in events]


def submit_legacy_elimination(
    core: CMBSCore,
    probe_id: str,
    observable_id: str,
    eliminated_hypotheses: Iterable[str],
) -> ProbeResult:
    """
    Convenience function for submitting a single legacy elimination event.
    """
    return core.submit_probe_result(
        probe_id=probe_id,
        observable_id=observable_id,
        eliminated=set(eliminated_hypotheses),
    )
