"""
Tests for ``ReinstatingMaskReducer`` (``"v2_mask_reinstate"``).

Namespaced invariants, pending slots in the test matrix:

- INV-R1  a reinstate targets exactly one in-force, accepted elimination
          envelope; each (seq, h) pair is reinstated at most once; a subset
          outside the asserted set is rejected.
- INV-R2  h survives iff no in-force pair names it (reinstating one of two
          killers does not revive h).
- INV-R3  the log only grows; survivors grow only via reinstate and shrink
          only via elimination.
- INV-R4  reinstatement leaves ``attrs`` unchanged.
- INV-O1  net progress ≡ |eliminated_now \\ dead_at_open|; kill-then-reinstate
          in scope nets 0; pre-open kills are inert both ways; never < 0.
- INV-O2  a closed obligation record is unchanged by any later op.

Plus the v1 compatibility guarantees: the v1 reducer's behaviour and state
hashes are byte-identical to before, and ``Session.recover`` picks the
reducer from the stored version.
"""

import json
import random

import pytest

from cmbs import (
    OBLIGATION_GROSS,
    OBLIGATION_NET,
    InMemoryOpLogStore,
    MaskMeetTombstoneReducer,
    OperationSpec,
    ReinstatingMaskReducer,
    Session,
    reducer_for_version,
    registered_reducer_versions,
)
from cmbs.reducer import KIND_ELIMINATION, KIND_REINSTATEMENT, KIND_UNKNOWN


def v2(ids=("H1", "H2", "H3", "H4"), **kw) -> Session:
    return Session(hypothesis_ids=set(ids), reducer=ReinstatingMaskReducer(), **kw)


def probe(s: Session, pid: str, elim):
    return s.submit_probe_result(probe_id=pid, observable_id=f"obs:{pid}", eliminated=set(elim))


# =============================================================================
# Reinstatement semantics
# =============================================================================


class TestReinstate:
    def test_reinstate_revives_a_singly_killed_hypothesis(self):
        s = v2()
        probe(s, "P1", {"H1", "H2"})
        assert s.survivors == {"H3", "H4"}

        r = s.reinstate_probe("P1")

        assert r.accepted is True
        assert r.voided == {"H1", "H2"}
        assert r.revived == {"H1", "H2"}
        assert s.survivors == {"H1", "H2", "H3", "H4"}
        assert s.snapshot().eliminated == frozenset()

    def test_inv_r2_two_killers_reinstating_one_leaves_h_dead(self):
        s = v2()
        probe(s, "P1", {"H1"})
        r2 = probe(s, "P2", {"H1"})
        assert r2.already_eliminated == {"H1"}  # facade view unchanged

        r = s.reinstate_probe("P1")

        assert r.accepted is True
        assert r.voided == {"H1"}
        assert r.revived == frozenset()  # P2 still holds it
        assert "H1" not in s.survivors
        assert s.snapshot().killers("H1") == {2}

        assert s.reinstate_probe("P2").revived == {"H1"}
        assert "H1" in s.survivors
        assert s.snapshot().killers("H1") == frozenset()

    def test_reinstate_by_seq_and_by_probe_id_agree(self):
        a, b = v2(session_id="s"), v2(session_id="s")
        for s in (a, b):
            probe(s, "P1", {"H1"})
        a.reinstate(1)
        b.reinstate_probe("P1")
        assert a.snapshot().state_hash == b.snapshot().state_hash

    def test_subset_reinstatement(self):
        s = v2()
        probe(s, "P1", {"H1", "H2", "H3"})

        r = s.reinstate(1, hypotheses={"H2"})

        assert r.accepted is True
        assert r.revived == {"H2"}
        assert s.survivors == {"H2", "H4"}
        assert s.snapshot().asserted_dead(1) == {"H1", "H2", "H3"}
        assert s.snapshot().in_force_pairs == {(1, "H1"), (1, "H3")}

        # Omitting the subset afterwards reinstates whatever is still in force.
        r = s.reinstate(1)
        assert r.revived == {"H1", "H3"}
        assert s.survivors == {"H1", "H2", "H3", "H4"}

    def test_inv_r1_each_pair_reinstated_at_most_once(self):
        s = v2()
        probe(s, "P1", {"H1", "H2"})
        assert s.reinstate(1, hypotheses={"H1"}).accepted is True

        again = s.reinstate(1, hypotheses={"H1"})
        assert again.accepted is False
        assert "already reinstated" in again.error

        # A mixed subset is rejected atomically: H2 is not voided either.
        mixed = s.reinstate(1, hypotheses={"H1", "H2"})
        assert mixed.accepted is False
        assert "H2" not in s.survivors

        assert s.reinstate(1).accepted is True
        whole_again = s.reinstate(1)
        assert whole_again.accepted is False
        assert "already fully reinstated" in whole_again.error

    def test_inv_r1_subset_outside_asserted_set_is_rejected(self):
        s = v2()
        probe(s, "P1", {"H1"})
        r = s.reinstate(1, hypotheses={"H1", "H2"})
        assert r.accepted is False
        assert "never asserted dead" in r.error and "H2" in r.error
        assert "H1" not in s.survivors

    def test_inv_r1_invalid_targets_are_rejected_and_logged(self):
        s = v2()
        probe(s, "P1", {"H1"})  # seq 1
        s.enter_obligation("O")  # seq 2, not an elimination
        probe(s, "P1", {"H2"})  # seq 3, rejected duplicate
        probe(s, "P2", set())  # seq 4, asserted nothing

        cases = {
            0: "out of range",
            99: "out of range",
            2: "not an accepted elimination",
            3: "not an accepted elimination",
            4: "not an accepted elimination",
        }
        for seq, fragment in cases.items():
            r = s.reinstate(seq)
            assert r.accepted is False, seq
            assert fragment in r.error, (seq, r.error)

        assert s.reinstate_probe("nope").error.startswith("unknown probe_id")
        both = s.append(OperationSpec(op_type="reinstate", payload={"seq": 1, "probe_id": "P1"}))
        assert both.envelope.accepted is False
        neither = s.append(OperationSpec(op_type="reinstate", payload={}))
        assert neither.envelope.accepted is False
        bad_seq = s.append(OperationSpec(op_type="reinstate", payload={"seq": "1"}))
        assert bad_seq.envelope.accepted is False
        empty = s.append(OperationSpec(op_type="reinstate", payload={"seq": 1, "hypotheses": []}))
        assert empty.envelope.accepted is False

        # Every one of those attempts is in the log as a rejected envelope.
        rejected = [op for op in s.operations() if op.op_type == "reinstate"]
        assert len(rejected) == len(cases) + 5
        assert all(op.accepted is False for op in rejected)
        assert "H1" not in s.survivors

    def test_reinstate_does_not_unconsume_probe_id(self):
        s = v2()
        probe(s, "P1", {"H1"})
        before = s.consumed_probes
        s.reinstate_probe("P1")
        assert s.consumed_probes == before == {"P1"}
        assert probe(s, "P1", {"H1"}).accepted is False  # INV-3 still holds
        assert "H1" in s.survivors

    def test_inv_r4_attrs_survive_reinstating_an_assert(self):
        s = v2()
        r = s.append(
            OperationSpec(op_type="assert", payload={"eliminate": ["H1"], "set": {"color": "red"}})
        )
        assert r.envelope.accepted and s.snapshot().attrs == {"color": "red"}

        assert s.reinstate(1).revived == {"H1"}

        assert s.snapshot().attrs == {"color": "red"}
        # A later refine still reads the attribute.
        s.append(
            OperationSpec(
                op_type="refine",
                payload={"if_attr": "color", "equals": "red", "eliminate": ["H2"]},
            )
        )
        assert "H2" not in s.survivors

    def test_false_condition_refine_asserts_nothing(self):
        s = v2()
        r = s.append(
            OperationSpec(
                op_type="refine",
                payload={"if_attr": "color", "equals": "red", "eliminate": ["H1"]},
            )
        )
        assert r.envelope.accepted is True
        assert s.snapshot().asserted_pairs == frozenset()
        assert s.reinstate(1).accepted is False

    def test_out_of_universe_ids_are_not_recorded(self):
        s = v2()
        probe(s, "P1", {"H1", "NOPE"})
        assert s.snapshot().asserted_dead(1) == {"H1"}

    def test_reinstate_reason_is_recorded_opaque(self):
        s = v2()
        probe(s, "P1", {"H1"})
        s.reinstate_probe("P1", reason="answer stream flagged inconsistent")
        assert s.operations()[-1].payload["reason"] == "answer stream flagged inconsistent"

    def test_reinstate_restores_position_digest(self):
        s = v2()
        top = s.position_digest
        probe(s, "P1", {"H1"})
        assert s.position_digest != top
        s.reinstate_probe("P1")
        assert s.position_digest == top

    def test_inv_r3_survivors_change_only_by_elimination_and_reinstate(self):
        s = v2()
        prev = s.survivors
        probe(s, "P1", {"H1"})
        s.enter_obligation("O")
        s.declare_conclusion("C")
        s.append(OperationSpec(op_type="branch_note", payload={"text": "x"}))
        s.reinstate_probe("P1")
        s.request_termination()
        for op in s.operations():
            cur = s.reducer.reduce(
                s.initial_hypotheses, s.operations(to_seq=op.seq), session_id=s.session_id
            ).survivors
            kind = s.reducer.classify(op.op_type)
            if cur > prev:
                assert kind == KIND_REINSTATEMENT
            elif cur < prev:
                assert kind == KIND_ELIMINATION
            prev = cur


# =============================================================================
# Vocabulary and migration
# =============================================================================


class TestVocabulary:
    def test_retired_ops_are_rejected_with_a_reason(self):
        s = v2()
        for op_type in ("retract", "tombstone"):
            r = s.append(OperationSpec(op_type=op_type, payload={"eliminate": ["H1"]}))
            assert r.envelope.accepted is False
            assert "retired" in r.envelope.rejected_reason
        assert s.survivors == {"H1", "H2", "H3", "H4"}

    def test_unknown_ops_remain_silent_no_ops(self):
        s = v2()
        before = s.snapshot()
        r = s.append(OperationSpec(op_type="branch_note", payload={"text": "x"}))
        assert r.envelope.accepted is True
        assert s.survivors == before.survivors
        assert s.snapshot().asserted_pairs == before.asserted_pairs

    def test_retired_ops_still_eliminate_under_v1(self):
        s = Session(hypothesis_ids={"H1", "H2"})
        r = s.append(OperationSpec(op_type="retract", payload={"eliminate": ["H1"]}))
        assert r.envelope.accepted is True
        assert s.survivors == {"H2"}

    def test_classify(self):
        r = ReinstatingMaskReducer()
        assert r.classify("reinstate") == KIND_REINSTATEMENT
        assert r.classify("probe_result") == KIND_ELIMINATION
        assert r.classify("retract") == KIND_UNKNOWN
        assert r.classify("tombstone") == KIND_UNKNOWN
        assert MaskMeetTombstoneReducer().classify("reinstate") == KIND_UNKNOWN

    def test_reinstate_facade_refuses_a_reducer_without_support(self):
        s = Session(hypothesis_ids={"H1"})
        probe(s, "P1", {"H1"})
        with pytest.raises(NotImplementedError, match="does not support reinstatement"):
            s.reinstate_probe("P1")
        with pytest.raises(NotImplementedError):
            s.reinstate(1)
        assert s.head_seq == 1  # nothing was appended

    def test_versions_are_distinct(self):
        assert ReinstatingMaskReducer.version == "v2_mask_reinstate"
        assert ReinstatingMaskReducer.version != MaskMeetTombstoneReducer.version


# =============================================================================
# Obligations: gross vs net
# =============================================================================


class TestObligationSemantics:
    def test_default_semantics_is_net(self):
        s = v2()
        s.enter_obligation("O", 1)
        assert s.snapshot().obligation("O").semantics == OBLIGATION_NET

    def test_invalid_semantics_rejected(self):
        s = v2()
        r = s.enter_obligation("O", 1, semantics="fuzzy")
        assert r.envelope.accepted is False
        assert "semantics" in r.envelope.rejected_reason
        assert s.active_obligations == frozenset()

    def test_v1_ignores_semantics(self):
        s = Session(hypothesis_ids={"H1", "H2"})
        assert s.enter_obligation("O", 1, semantics="net").envelope.accepted is True
        entry = s.snapshot().obligation("O")
        assert entry.open_seq == 0 and entry.semantics == OBLIGATION_GROSS
        # And the payload is untouched when semantics is not given.
        s.enter_obligation("P", 1)
        assert "semantics" not in s.operations()[-1].payload

    def test_inv_o1_kill_then_reinstate_satisfies_gross_not_net(self):
        s = v2()
        s.enter_obligation("net", 1, semantics="net")
        s.enter_obligation("gross", 1, semantics="gross")
        probe(s, "P1", {"H1"})
        assert s.obligation_progress("net") == 1
        assert s.obligation_progress("gross") == 1

        s.reinstate_probe("P1")

        assert s.obligation_progress("net") == 0
        assert s.obligation_progress("gross") == 1
        net_exit = s.request_obligation_exit("net")
        assert net_exit.permitted is False
        assert "insufficient net progress" in net_exit.error
        assert s.request_obligation_exit("gross").permitted is True

    def test_inv_o1_pre_open_kills_are_inert_both_ways(self):
        s = v2()
        probe(s, "P1", {"H1"})  # before the obligation opens
        s.enter_obligation("O", 1)  # dead_at_open = {H1}
        assert s.snapshot().obligation("O").dead_at_open == {"H1"}
        assert s.obligation_progress("O") == 0

        # Reinstating a pre-open kill cannot earn progress...
        s.reinstate_probe("P1")
        assert s.obligation_progress("O") == 0
        # ...and killing it again in scope earns no net credit either,
        # because it was never in S(open). Gross counts that kill.
        s.enter_obligation("G", 1, semantics="gross")
        probe(s, "P2", {"H1"})
        assert s.obligation_progress("O") == 0
        assert s.obligation_progress("G") == 1
        assert s.request_obligation_exit("O").permitted is False

    def test_inv_o1_net_is_hypothesis_level(self):
        s = v2()
        s.enter_obligation("O", 2)
        probe(s, "P1", {"H1"})
        probe(s, "P2", {"H1"})  # second killer of the same hypothesis
        assert s.obligation_progress("O") == 1
        assert s.request_obligation_exit("O").permitted is False
        probe(s, "P3", {"H2"})
        assert s.obligation_progress("O") == 2
        assert s.request_obligation_exit("O").permitted is True

    def test_inv_o1_net_progress_is_never_negative(self):
        s = v2()
        probe(s, "P1", {"H1", "H2"})
        s.enter_obligation("O", 1)
        s.reinstate_probe("P1")
        assert s.obligation_progress("O") == 0
        assert s.snapshot().entropy > 0

    def test_gross_may_exceed_universe_size(self):
        s = v2(ids=("H1",))
        s.enter_obligation("G", 1, semantics="gross")
        probe(s, "P1", {"H1"})
        s.reinstate_probe("P1")
        probe(s, "P2", {"H1"})
        assert s.obligation_progress("G") == 2 > len(s.initial_hypotheses)

    def test_closed_tuple_holds_successful_exits_only(self):
        s = v2()
        s.enter_obligation("O", 1)
        assert s.request_obligation_exit("O").permitted is False  # rejected attempt
        assert s.closed_obligations == ()
        probe(s, "P1", {"H1"})
        assert s.request_obligation_exit("O").permitted is True

        (closed,) = s.closed_obligations
        assert closed.obligation_id == "O"
        assert closed.open_seq == 1
        assert closed.exit_seq == 4
        assert closed.semantics == OBLIGATION_NET
        assert closed.min_eliminations == 1
        assert closed.progress_at_exit == 1
        assert s.active_obligations == frozenset()

    def test_inv_o2_closed_record_unchanged_by_later_reinstate(self):
        s = v2()
        s.enter_obligation("O", 1)
        probe(s, "P1", {"H1"})
        s.request_obligation_exit("O")
        closed_before = s.closed_obligations

        s.reinstate_probe("P1")
        probe(s, "P2", {"H2", "H3"})

        assert s.closed_obligations == closed_before
        assert s.closed_obligations[0].progress_at_exit == 1

    def test_reentry_yields_two_closed_records_sharing_an_id(self):
        s = v2()
        s.enter_obligation("O", 1)
        probe(s, "P1", {"H1"})
        s.request_obligation_exit("O")
        assert s.enter_obligation("O", 1).envelope.accepted is True
        active = s.snapshot().obligation("O")
        assert active.open_seq == 4
        assert active.dead_at_open == {"H1"}
        assert s.request_obligation_exit("O").permitted is False  # scope restarted
        probe(s, "P2", {"H2"})
        assert s.request_obligation_exit("O").permitted is True

        assert [(c.obligation_id, c.open_seq) for c in s.closed_obligations] == [("O", 1), ("O", 4)]
        assert s.snapshot().obligation("O") is None

    def test_v1_keeps_no_closed_records(self):
        s = Session(hypothesis_ids={"H1"})
        s.enter_obligation("O", 1)
        probe(s, "P1", {"H1"})
        assert s.request_obligation_exit("O").permitted is True
        assert s.closed_obligations == ()


# =============================================================================
# Hashing, replay, recovery
# =============================================================================


class TestHashingReplayRecovery:
    # Computed from the v0.1.0 reducer before reinstatement support existed.
    # Pinning it guarantees the new snapshot fields leave v1 hashes untouched.
    V1_PINNED_HASH = "493933086f613a3c46894bc842760546188c14834930a0ab24fdb5cebd0a2e73"

    def test_v1_state_hash_is_byte_identical_to_before(self):
        s = Session(hypothesis_ids={"H1", "H2", "H3"}, session_id="pinned", stability_window=2)
        probe(s, "P1", {"H1"})
        s.enter_obligation("O", 1)
        probe(s, "P1", {"H2"})  # rejected duplicate
        s.append(OperationSpec(op_type="assert", payload={"eliminate": ["H2"], "set": {"k": "v"}}))
        s.declare_conclusion("C")
        s.declare_conclusion("C")
        s.request_termination()
        assert s.snapshot().state_hash == self.V1_PINNED_HASH

    def test_v2_hash_differs_from_v1_for_the_same_log(self):
        a = Session(hypothesis_ids={"H1"}, session_id="s")
        b = v2(ids=("H1",), session_id="s")
        assert a.snapshot().state_hash != b.snapshot().state_hash

    def test_hash_covers_reinstatement_and_closed_records(self):
        s = v2()
        probe(s, "P1", {"H1"})
        h_killed = s.snapshot().state_hash
        s.reinstate_probe("P1")
        h_revived = s.snapshot().state_hash
        # Same survivors as the fresh session, but a different log position
        # and a non-empty record set, so the state hash moved while the
        # position digest is back where it started.
        fresh = v2(session_id=s.session_id)
        assert h_revived not in {h_killed, fresh.snapshot().state_hash}
        assert s.position_digest == fresh.position_digest

    def test_full_reduce_equals_incremental_state(self):
        s = v2(stability_window=2)
        probe(s, "P1", {"H1", "H2"})
        s.enter_obligation("N", 1)
        s.enter_obligation("G", 1, semantics="gross")
        probe(s, "P2", {"H2"})
        s.reinstate_probe("P1")
        s.reinstate(1)  # rejected: already fully reinstated
        probe(s, "P3", {"H3"})
        s.request_obligation_exit("N")
        s.request_obligation_exit("G")
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

    def test_recover_picks_the_reducer_from_the_stored_version(self):
        store = InMemoryOpLogStore()
        s = v2(store=store)
        probe(s, "P1", {"H1", "H2"})
        s.reinstate(1, hypotheses={"H1"})

        r = Session.recover(store, s.session_id)

        assert isinstance(r.reducer, ReinstatingMaskReducer)
        assert r.snapshot() == s.snapshot()
        assert r.reinstate_probe("P1").revived == {"H2"}  # key_seqs survived recovery

    def test_recover_v1_still_defaults_to_v1(self):
        store = InMemoryOpLogStore()
        s = Session(hypothesis_ids={"H1"}, store=store)
        r = Session.recover(store, s.session_id)
        assert isinstance(r.reducer, MaskMeetTombstoneReducer)
        assert not isinstance(r.reducer, ReinstatingMaskReducer)

    def test_recover_with_mismatched_explicit_reducer_raises(self):
        store = InMemoryOpLogStore()
        s = v2(store=store)
        with pytest.raises(ValueError, match="cannot replay"):
            Session.recover(store, s.session_id, reducer=MaskMeetTombstoneReducer())

    def test_recover_unregistered_version_raises(self):
        class Other(MaskMeetTombstoneReducer):
            version = "v9_unregistered"

        store = InMemoryOpLogStore()
        s = Session(hypothesis_ids={"H1"}, store=store, reducer=Other())
        with pytest.raises(ValueError, match="no reducer registered"):
            Session.recover(store, s.session_id)
        # Passing it explicitly still works.
        assert Session.recover(store, s.session_id, reducer=Other()).survivors == {"H1"}

    def test_registry_lists_both_shipped_versions(self):
        versions = registered_reducer_versions()
        assert "v1_mask_meet_tombstone" in versions
        assert "v2_mask_reinstate" in versions
        assert isinstance(reducer_for_version("v2_mask_reinstate"), ReinstatingMaskReducer)

    def test_snapshot_to_dict_round_trips_json(self):
        s = v2()
        probe(s, "P1", {"H1", "H2"})
        s.enter_obligation("O", 1)
        s.reinstate(1, hypotheses={"H1"})
        d = s.snapshot().to_dict()
        assert json.loads(json.dumps(d)) == d
        assert d["asserted_pairs"] == [[1, "H1"], [1, "H2"]]
        assert d["reinstated_pairs"] == [[1, "H1"]]
        assert d["key_seqs"] == {"P1": 1}
        assert d["obligations"][0]["semantics"] == "net"
        assert d["obligations"][0]["dead_at_open"] == ["H1", "H2"]
        assert d["obligations"][0]["progress"] == 0


# =============================================================================
# Property test: random op sequences
# =============================================================================


def _random_session(seed: int) -> Session:
    rng = random.Random(seed)
    universe = [f"H{i}" for i in range(6)]
    s = v2(ids=universe)
    n_probe = 0
    for _ in range(60):
        roll = rng.random()
        if roll < 0.40:
            n_probe += 1
            probe(s, f"P{n_probe}", rng.sample(universe, rng.randint(0, 3)))
        elif roll < 0.65:
            seq = rng.randint(0, s.head_seq + 1)
            subset = None
            if rng.random() < 0.3:
                subset = set(rng.sample(universe, rng.randint(0, 2)))
            s.reinstate(seq, subset)
        elif roll < 0.80:
            s.enter_obligation(
                rng.choice("ABC"),
                rng.randint(0, 3),
                semantics=rng.choice([OBLIGATION_GROSS, OBLIGATION_NET]),
            )
        elif roll < 0.95:
            s.request_obligation_exit(rng.choice("ABC"))
        else:
            s.append(OperationSpec(op_type="branch_note", payload={"i": rng.random()}))
    return s


@pytest.mark.parametrize("seed", range(12))
def test_random_sequences_keep_the_invariants(seed):
    s = _random_session(seed)
    snap = s.snapshot()
    universe = s.initial_hypotheses

    # INV-R1: reinstated pairs are a subset of asserted pairs.
    assert snap.reinstated_pairs <= snap.asserted_pairs
    # INV-R2: survivors are exactly the hypotheses with no in-force pair.
    held = {h for _, h in snap.in_force_pairs}
    assert snap.eliminated == held
    assert snap.survivors == universe - held
    # INV-O1: net progress is the set difference against dead_at_open.
    for entry in snap.obligations:
        if entry.semantics == OBLIGATION_NET:
            assert entry.progress(snap.eliminated) == len(snap.eliminated - entry.dead_at_open)
        assert entry.progress(snap.eliminated) >= 0
    # Replay fidelity, including rejected envelopes.
    replayed = s.reducer.reduce(universe, s.operations(), session_id=s.session_id)
    assert replayed == snap
    # Closed records are frozen: each equals the record computed at its exit.
    for closed in snap.closed_obligations:
        at_exit = s.reducer.reduce(
            universe, s.operations(to_seq=closed.exit_seq), session_id=s.session_id
        )
        assert closed in at_exit.closed_obligations
    # INV-R3 and the conditional INV-5a along the whole log.
    prev = universe
    for op in s.operations():
        cur = s.reducer.reduce(universe, s.operations(to_seq=op.seq), session_id=s.session_id)
        kind = s.reducer.classify(op.op_type)
        if cur.survivors > prev:
            assert kind == KIND_REINSTATEMENT and op.accepted
        elif cur.survivors < prev:
            assert kind == KIND_ELIMINATION and op.accepted
        prev = cur.survivors
