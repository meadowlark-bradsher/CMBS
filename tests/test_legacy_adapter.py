"""Tests for the legacy replay adapter shim."""

from cmbs import Session
from cmbs.adapters.legacy import (
    LegacyEliminationEvent,
    LegacyReplayAdapter,
    submit_legacy_elimination,
)


def test_legacy_adapter_submits_elimination_event():
    session = Session(hypothesis_ids={"H1", "H2"})
    adapter = LegacyReplayAdapter(session)

    result = adapter.submit_elimination_event(
        LegacyEliminationEvent(
            probe_id="legacy:probe:001",
            observable_id="legacy:obs:alpha",
            eliminated_hypotheses={"H1"},
        )
    )

    assert result.accepted is True
    assert session.survivors == {"H2"}
    assert adapter.session is session


def test_legacy_adapter_opaque_ids_no_validation():
    session = Session(hypothesis_ids={"H1", "H2"})
    adapter = LegacyReplayAdapter(session)

    result = adapter.submit_elimination_event(
        LegacyEliminationEvent(
            probe_id="weird/probe/id",
            observable_id="obs::??::id",
            eliminated_hypotheses={"H9"},
        )
    )

    assert result.accepted is True
    assert session.survivors == {"H1", "H2"}


def test_legacy_adapter_passes_duplicate_probes_to_session():
    session = Session(hypothesis_ids={"H1", "H2"})
    adapter = LegacyReplayAdapter(session)

    event = LegacyEliminationEvent(
        probe_id="dup-probe",
        observable_id="obs-1",
        eliminated_hypotheses={"H2"},
    )

    first = adapter.submit_elimination_event(event)
    second = adapter.submit_elimination_event(event)

    assert first.accepted is True
    assert second.accepted is False
    assert session.survivors == {"H1"}


def test_legacy_adapter_batch_and_audit_trail():
    session = Session(hypothesis_ids={"H1", "H2", "H3"})
    adapter = LegacyReplayAdapter(session, source_id="legacy://batch")

    results = adapter.submit_elimination_events(
        [
            LegacyEliminationEvent("p1", "o1", {"H1"}),
            LegacyEliminationEvent("p2", "o2", {"H2"}),
        ]
    )

    assert [r.accepted for r in results] == [True, True]
    ops = session.operations()
    assert [op.idempotency_key for op in ops] == ["p1", "p2"]
    assert all(op.source_id == "legacy://batch" for op in ops)
    assert ops[1].payload["observable_id"] == "o2"


def test_submit_legacy_elimination_convenience():
    session = Session(hypothesis_ids={"H1", "H2"})
    result = submit_legacy_elimination(session, "p", "o", ["H2"])
    assert result.accepted is True
    assert session.survivors == {"H1"}
