"""
Substrate-level tests for the unified ``Session`` kernel.

``test_session_invariants.py`` pins the v0 workflow invariants. This file
covers what the v2 substrate adds underneath them: the op log as audit
trail, deterministic hashing, idempotent retries, the persistence SPI,
and recovery.
"""

import math

import pytest

from cmbs.operations import OperationEnvelope, OperationSpec
from cmbs.reducer import (
    KIND_CONCLUSION,
    KIND_ELIMINATION,
    KIND_OBLIGATION,
    KIND_TERMINATION,
    KIND_UNKNOWN,
    MaskMeetTombstoneReducer,
    Reducer,
)
from cmbs.session import Session
from cmbs.snapshot import OntologyBundle
from cmbs.store import InMemoryOpLogStore, OpLogStore


def _probe(session, pid, elim=()):
    return session.submit_probe_result(probe_id=pid, observable_id=f"obs-{pid}", eliminated=set(elim))


# -----------------------------------------------------------------------------
# Op log as audit trail
# -----------------------------------------------------------------------------


class TestOpLog:
    def test_rejected_envelopes_enter_the_log(self):
        s = Session(hypothesis_ids={"H1", "H2"})
        _probe(s, "P1", {"H1"})
        r = _probe(s, "P1", {"H2"})

        assert r.accepted is False
        assert "duplicate" in r.error
        ops = s.operations()
        assert [op.seq for op in ops] == [1, 2]
        assert ops[1].accepted is False
        assert ops[1].rejected_reason == r.error
        assert ops[1].idempotency_key == "P1"
        assert s.survivors == {"H2"}

    def test_seq_advances_and_hash_changes_on_rejection(self):
        s = Session(hypothesis_ids={"H1", "H2"})
        h1 = _probe_hash(s, "P1")
        h2 = _probe_hash(s, "P1")

        assert s.head_seq == 2
        assert h1 != h2  # the hash names a log position, not just a belief

    def test_seq_is_contiguous_across_facade_and_append(self):
        s = Session(hypothesis_ids={"H1", "H2"})
        _probe(s, "P1")
        s.enter_obligation("O1")
        s.append(OperationSpec(op_type="branch_note", payload={"text": "hi"}))
        s.declare_conclusion("C")
        s.request_termination()
        assert [op.seq for op in s.operations()] == [1, 2, 3, 4, 5]

    def test_operations_range_is_inclusive_and_one_indexed(self):
        s = Session(hypothesis_ids={"H1"})
        for i in range(5):
            _probe(s, f"P{i}")
        assert [op.seq for op in s.operations(2, 4)] == [2, 3, 4]
        assert [op.seq for op in s.operations(from_seq=4)] == [4, 5]
        assert [op.seq for op in s.operations(to_seq=2)] == [1, 2]

    def test_payload_is_copied_on_append(self):
        s = Session(hypothesis_ids={"H1", "H2"})
        payload = {"eliminate": ["H1"]}
        s.append(OperationSpec(op_type="retract", payload=payload))
        payload["eliminate"].append("H2")
        assert list(s.operations()[0].payload["eliminate"]) == ["H1"]

    def test_source_id_and_provenance_are_recorded_opaque(self):
        s = Session(hypothesis_ids={"H1"})
        s.submit_probe_result(
            probe_id="P1",
            observable_id="O1",
            eliminated=set(),
            source_id="agent-7",
            provenance={"tool": "grep", "exit": 0},
        )
        op = s.operations()[0]
        assert op.source_id == "agent-7"
        assert op.payload["provenance"] == {"tool": "grep", "exit": 0}

    def test_empty_string_probe_id_is_a_real_key(self):
        s = Session(hypothesis_ids={"H1"})
        assert _probe(s, "").accepted is True
        assert _probe(s, "").accepted is False
        assert "" in s.consumed_probes


def _probe_hash(session, pid):
    return session.append(
        OperationSpec(op_type="probe_result", payload={"eliminate": []}, idempotency_key=pid)
    ).state_hash_after


# -----------------------------------------------------------------------------
# Idempotent retry via op_id
# -----------------------------------------------------------------------------


class TestOpIdRetry:
    def test_same_op_id_returns_original_without_appending(self):
        s = Session(hypothesis_ids={"H1", "H2", "H3"})
        spec = OperationSpec(op_type="retract", payload={"eliminate": ["H1"]}, op_id="op-1")
        first = s.append(spec)
        _probe(s, "P1", {"H2"})
        again = s.append(spec)

        assert again.envelope is first.envelope
        assert again.state_hash_after == first.state_hash_after
        assert again.survivors_count_after == 2  # state as of seq 1, not head
        assert s.head_seq == 2

    def test_op_id_retry_survives_recovery(self):
        store = InMemoryOpLogStore()
        s = Session(hypothesis_ids={"H1", "H2"}, store=store)
        spec = OperationSpec(op_type="retract", payload={"eliminate": ["H1"]}, op_id="op-1")
        first = s.append(spec)

        r = Session.recover(store, s.session_id)
        again = r.append(spec)
        assert again.envelope == first.envelope
        assert r.head_seq == 1


# -----------------------------------------------------------------------------
# Deterministic hashing
# -----------------------------------------------------------------------------


class TestStateHash:
    def test_same_log_same_hash(self):
        a = Session(hypothesis_ids={"H1", "H2", "H3"}, session_id="sid")
        b = Session(hypothesis_ids={"H1", "H2", "H3"}, session_id="sid")
        for s in (a, b):
            _probe(s, "P1", {"H1"})
            s.enter_obligation("O1", 1)
            s.declare_conclusion("C")
        assert a.snapshot().state_hash == b.snapshot().state_hash

    def test_hash_covers_session_id(self):
        a = Session(hypothesis_ids={"H1"}, session_id="a")
        b = Session(hypothesis_ids={"H1"}, session_id="b")
        assert a.snapshot().state_hash != b.snapshot().state_hash

    def test_hash_covers_reducer_version(self):
        class Renamed(MaskMeetTombstoneReducer):
            version = "v1_mask_meet_tombstone__renamed"

        a = Session(hypothesis_ids={"H1"}, session_id="s")
        b = Session(hypothesis_ids={"H1"}, session_id="s", reducer=Renamed())
        assert a.snapshot().state_hash != b.snapshot().state_hash

    def test_order_sensitivity(self):
        a = Session(hypothesis_ids={"H1", "H2"}, session_id="s")
        b = Session(hypothesis_ids={"H1", "H2"}, session_id="s")
        _probe(a, "P1", {"H1"})
        _probe(a, "P2", {"H2"})
        _probe(b, "P2", {"H2"})
        _probe(b, "P1", {"H1"})
        # Same belief, same position, but consumed keys arrived in a
        # different order — belief state is identical so hashes agree.
        assert a.survivors == b.survivors == frozenset()
        assert a.snapshot().state_hash == b.snapshot().state_hash

    def test_full_reduce_equals_incremental_state(self):
        s = Session(hypothesis_ids={"H1", "H2", "H3"}, stability_window=2)
        _probe(s, "P1", {"H1"})
        s.enter_obligation("O1", 1)
        _probe(s, "P1", {"H2"})  # rejected
        s.declare_conclusion("C")
        s.declare_conclusion("C")
        s.request_termination()

        replayed = s.reducer.reduce(
            s.initial_hypotheses,
            s.operations(),
            session_id=s.session_id,
            stability_window=s.stability_window,
        )
        assert replayed == s.snapshot()


# -----------------------------------------------------------------------------
# Reducer semantics beyond the v0 facade
# -----------------------------------------------------------------------------


class TestReducerSemantics:
    def test_is_runtime_checkable_reducer(self):
        assert isinstance(MaskMeetTombstoneReducer(), Reducer)

    def test_classify(self):
        r = MaskMeetTombstoneReducer()
        assert r.classify("probe_result") == KIND_ELIMINATION
        assert r.classify("retract") == KIND_ELIMINATION
        assert r.classify("refine") == KIND_ELIMINATION
        assert r.classify("enter_obligation") == KIND_OBLIGATION
        assert r.classify("exit_obligation") == KIND_OBLIGATION
        assert r.classify("declare_conclusion") == KIND_CONCLUSION
        assert r.classify("request_termination") == KIND_TERMINATION
        assert r.classify("branch_note") == KIND_UNKNOWN

    def test_unknown_op_is_accepted_and_changes_no_state(self):
        s = Session(hypothesis_ids={"H1", "H2"})
        before = s.snapshot()
        res = s.append(OperationSpec(op_type="branch_note", payload={"text": "x"}))
        after = s.snapshot()

        assert res.envelope.accepted is True
        assert after.survivors == before.survivors
        assert after.obligations == before.obligations
        assert after.seq == before.seq + 1

    def test_assert_sets_attrs_and_refine_is_conditional(self):
        s = Session(hypothesis_ids={"H1", "H2", "H3", "H4"})
        s.append(
            OperationSpec(
                op_type="assert",
                payload={"eliminate": ["H1"], "set": {"color": "red"}},
            )
        )
        assert s.snapshot().attrs == {"color": "red"}

        s.append(
            OperationSpec(
                op_type="refine",
                payload={"if_attr": "color", "equals": "blue", "eliminate": ["H2"]},
            )
        )
        assert s.survivors == {"H2", "H3", "H4"}  # condition false, no-op

        s.append(
            OperationSpec(
                op_type="refine",
                payload={"if_attr": "color", "equals": "red", "eliminate": ["H2"]},
            )
        )
        assert s.survivors == {"H3", "H4"}

    def test_v2_eliminations_count_toward_obligations(self):
        s = Session(hypothesis_ids={"H1", "H2", "H3"})
        s.enter_obligation("O1", 1)
        s.append(OperationSpec(op_type="retract", payload={"eliminate": ["H1"]}))
        assert s.request_obligation_exit("O1").permitted is True

    def test_unknown_hypothesis_ids_are_ignored(self):
        s = Session(hypothesis_ids={"H1", "H2"})
        r = _probe(s, "P1", {"H1", "NOPE"})
        assert r.accepted is True
        assert r.eliminated == {"H1"}
        assert r.already_eliminated == frozenset()
        assert s.survivors == {"H2"}

    def test_probe_result_reports_already_eliminated(self):
        s = Session(hypothesis_ids={"H1", "H2", "H3"})
        _probe(s, "P1", {"H1"})
        r = _probe(s, "P2", {"H1", "H2"})
        assert r.eliminated == {"H2"}
        assert r.already_eliminated == {"H1"}

    def test_reentering_active_obligation_is_rejected(self):
        s = Session(hypothesis_ids={"H1", "H2"})
        assert s.enter_obligation("O1", 1).envelope.accepted is True
        again = s.enter_obligation("O1", 5)
        assert again.envelope.accepted is False
        assert "already active" in again.envelope.rejected_reason
        assert s.snapshot().obligation("O1").min_eliminations == 1

    def test_obligation_can_be_reentered_after_exit(self):
        s = Session(hypothesis_ids={"H1", "H2", "H3"})
        s.enter_obligation("O1", 1)
        _probe(s, "P1", {"H1"})
        assert s.request_obligation_exit("O1").permitted is True
        assert s.enter_obligation("O1", 1).envelope.accepted is True
        # scope restarts: the earlier elimination does not carry over
        assert s.request_obligation_exit("O1").permitted is False

    def test_negative_min_eliminations_rejected(self):
        s = Session(hypothesis_ids={"H1"})
        assert s.enter_obligation("O1", -1).envelope.accepted is False
        assert s.active_obligations == frozenset()

    def test_zero_min_eliminations_exits_immediately(self):
        s = Session(hypothesis_ids={"H1"})
        s.enter_obligation("O1", 0)
        assert s.request_obligation_exit("O1").permitted is True

    def test_termination_is_idempotent_and_does_not_freeze(self):
        s = Session(hypothesis_ids={"H1", "H2"})
        assert s.request_termination().permitted is True
        assert s.request_termination().permitted is True
        assert s.is_terminated is True
        assert _probe(s, "P1", {"H1"}).accepted is True
        assert s.survivors == {"H2"}

    def test_termination_rejection_reasons(self):
        s = Session(hypothesis_ids={"H1"}, stability_window=2)
        r = s.request_termination()
        assert r.permitted is False
        assert "shorter than stability window" in r.error
        s.declare_conclusion("A")
        s.declare_conclusion("B")
        r = s.request_termination()
        assert r.permitted is False
        assert "unstable" in r.error

    def test_malformed_facade_ops_are_rejected_not_raised(self):
        s = Session(hypothesis_ids={"H1"})
        r = s.append(OperationSpec(op_type="enter_obligation", payload={}))
        assert r.envelope.accepted is False
        r = s.append(OperationSpec(op_type="declare_conclusion", payload={"conclusion_id": 3}))
        assert r.envelope.accepted is False
        r = s.append(OperationSpec(op_type="retract", payload={"eliminate": "H1"}))
        assert r.envelope.accepted is False
        assert s.survivors == {"H1"}


# -----------------------------------------------------------------------------
# Construction and validation
# -----------------------------------------------------------------------------


class TestConstruction:
    def test_default_session_id_is_uuid_like_and_unique(self):
        a, b = Session(hypothesis_ids={"H"}), Session(hypothesis_ids={"H"})
        assert a.session_id != b.session_id
        assert len(a.session_id) == 36

    def test_ontology_is_stored_not_interpreted(self):
        ont = OntologyBundle(hypothesis_space_id="k8s", hypothesis_version="3")
        s = Session(hypothesis_ids={"H"}, ontology=ont)
        assert s.ontology is ont

    def test_hypothesis_ids_accepts_any_iterable(self):
        s = Session(hypothesis_ids=["H1", "H2", "H1"])
        assert s.survivors == {"H1", "H2"}
        assert s.entropy == pytest.approx(1.0)

    def test_non_string_hypothesis_id_rejected(self):
        with pytest.raises(TypeError):
            Session(hypothesis_ids={"H1", 2})

    def test_invalid_stability_window_rejected(self):
        with pytest.raises(ValueError):
            Session(hypothesis_ids={"H1"}, stability_window=-1)
        with pytest.raises(TypeError):
            Session(hypothesis_ids={"H1"}, stability_window=True)

    def test_append_rejects_bad_spec(self):
        s = Session(hypothesis_ids={"H1"})
        with pytest.raises(TypeError):
            s.append({"op_type": "retract"})
        with pytest.raises(ValueError):
            s.append(OperationSpec(op_type=""))

    def test_empty_universe(self):
        s = Session(hypothesis_ids=set())
        assert s.survivors == frozenset()
        assert s.entropy == 0.0
        assert _probe(s, "P1", {"H1"}).accepted is True

    def test_forbidden_execution_terms_absent_from_snapshot_and_results(self):
        forbidden = {"attempted", "successful", "failed", "pending", "executing", "running"}
        for cls in (Session, MaskMeetTombstoneReducer, InMemoryOpLogStore):
            for member in dir(cls):
                assert not any(t in member.lower() for t in forbidden), member


# -----------------------------------------------------------------------------
# Persistence SPI and recovery
# -----------------------------------------------------------------------------


class TestStoreAndRecovery:
    def test_in_memory_store_satisfies_protocol(self):
        assert isinstance(InMemoryOpLogStore(), OpLogStore)

    def test_duplicate_session_id_rejected_by_store(self):
        store = InMemoryOpLogStore()
        Session(hypothesis_ids={"H1"}, store=store, session_id="same")
        with pytest.raises(ValueError):
            Session(hypothesis_ids={"H1"}, store=store, session_id="same")

    def test_store_rejects_out_of_order_append(self):
        store = InMemoryOpLogStore()
        store.create_session("s", frozenset({"H1"}), None, 0, "v")
        env = OperationEnvelope(
            op_id="x", seq=2, op_type="retract", payload={}, source_id="",
            idempotency_key=None, accepted=True, rejected_reason=None, created_at=0.0,
        )
        with pytest.raises(ValueError):
            store.append("s", env)

    def test_store_unknown_session_raises_keyerror(self):
        store = InMemoryOpLogStore()
        with pytest.raises(KeyError):
            store.head_seq("nope")
        with pytest.raises(KeyError):
            store.recover("nope")

    def test_store_read_ops_validation(self):
        store = InMemoryOpLogStore()
        store.create_session("s", frozenset(), None, 0, "v")
        assert store.read_ops("s") == ()
        assert store.head_seq("s") == 0
        with pytest.raises(ValueError):
            store.read_ops("s", from_seq=0)

    def test_multiple_sessions_share_a_store(self):
        store = InMemoryOpLogStore()
        a = Session(hypothesis_ids={"H1", "H2"}, store=store)
        b = Session(hypothesis_ids={"H1", "H2"}, store=store)
        _probe(a, "P1", {"H1"})
        assert b.survivors == {"H1", "H2"}
        assert set(store.session_ids()) == {a.session_id, b.session_id}

    def test_recover_reproduces_full_snapshot(self):
        store = InMemoryOpLogStore()
        ont = OntologyBundle(hypothesis_space_id="x", hypothesis_version="1")
        s = Session(hypothesis_ids={"H1", "H2", "H3", "H4"}, store=store,
                    stability_window=2, ontology=ont, session_id="sid")
        _probe(s, "P1", {"H1"})
        s.enter_obligation("O1", 2)
        _probe(s, "P2", {"H2"})
        _probe(s, "P2", {"H3"})  # rejected duplicate
        s.declare_conclusion("C")
        s.append(OperationSpec(op_type="assert", payload={"set": {"k": "v"}}))

        r = Session.recover(store, "sid")

        assert r.snapshot() == s.snapshot()
        assert r.snapshot().state_hash == s.snapshot().state_hash
        assert r.head_seq == s.head_seq == 6
        assert r.ontology == ont
        assert r.stability_window == 2
        assert r.initial_hypotheses == s.initial_hypotheses
        assert r.snapshot().obligation("O1").eliminations_in_scope == 1
        assert r.entropy == pytest.approx(math.log2(2))

    def test_recovered_session_continues_the_same_log(self):
        store = InMemoryOpLogStore()
        s = Session(hypothesis_ids={"H1", "H2", "H3"}, store=store)
        _probe(s, "P1", {"H1"})

        r = Session.recover(store, s.session_id)
        assert _probe(r, "P1", {"H2"}).accepted is False  # key still consumed
        assert _probe(r, "P2", {"H2"}).accepted is True
        assert r.head_seq == 3
        assert store.head_seq(s.session_id) == 3

    def test_recover_under_wrong_reducer_version_raises(self):
        class Other(MaskMeetTombstoneReducer):
            version = "v9_other"

        store = InMemoryOpLogStore()
        s = Session(hypothesis_ids={"H1"}, store=store)
        with pytest.raises(ValueError, match="cannot replay"):
            Session.recover(store, s.session_id, reducer=Other())

    def test_recover_unknown_session_raises(self):
        with pytest.raises(KeyError):
            Session.recover(InMemoryOpLogStore(), "missing")

    def test_snapshot_to_dict_round_trips_json(self):
        import json

        s = Session(hypothesis_ids={"H1", "H2"}, stability_window=1)
        _probe(s, "P1", {"H1"})
        s.enter_obligation("O1", 1)
        d = s.snapshot().to_dict()
        assert json.loads(json.dumps(d)) == d
        assert d["survivors"] == ["H2"]
        assert d["active_obligations"] == ["O1"]
        assert d["stability_window"] == 1
        assert d["seq"] == 2
