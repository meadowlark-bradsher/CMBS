"""Tests for the legacy replay adapter shim."""

from cmbs.adapters.legacy import LegacyEliminationEvent, LegacyReplayAdapter
from cmbs.core import CMBSCore


def test_legacy_adapter_submits_elimination_event():
    core = CMBSCore(hypothesis_ids={"H1", "H2"})
    adapter = LegacyReplayAdapter(core)

    result = adapter.submit_elimination_event(
        LegacyEliminationEvent(
            probe_id="legacy:probe:001",
            observable_id="legacy:obs:alpha",
            eliminated_hypotheses={"H1"},
        )
    )

    assert result.accepted is True
    assert core.survivors == {"H2"}


def test_legacy_adapter_opaque_ids_no_validation():
    core = CMBSCore(hypothesis_ids={"H1", "H2"})
    adapter = LegacyReplayAdapter(core)

    result = adapter.submit_elimination_event(
        LegacyEliminationEvent(
            probe_id="weird/probe/id",
            observable_id="obs::??::id",
            eliminated_hypotheses={"H9"},
        )
    )

    assert result.accepted is True
    assert core.survivors == {"H1", "H2"}


def test_legacy_adapter_passes_duplicate_probes_to_core():
    core = CMBSCore(hypothesis_ids={"H1", "H2"})
    adapter = LegacyReplayAdapter(core)

    event = LegacyEliminationEvent(
        probe_id="dup-probe",
        observable_id="obs-1",
        eliminated_hypotheses={"H2"},
    )

    first = adapter.submit_elimination_event(event)
    second = adapter.submit_elimination_event(event)

    assert first.accepted is True
    assert second.accepted is False
    assert core.survivors == {"H1"}
