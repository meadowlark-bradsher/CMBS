"""
Tests for the v0.2.0 Phase 3 additions to ``ReinstatingMaskReducer``: the
bounded model-facing view, the reinstatement budget, and the optional
``weight`` / ``reason`` on eliminations.

Namespaced invariants, pending slots in the test matrix:

- INV-B1  with ``max_reinstates=n``, the (n+1)-th reinstate is rejected
          with a reason and logged; state is unchanged.
- INV-B2  with ``max_reinstated_pairs=m``, a reinstate that would bring
          ``|reinstated_pairs|`` past m is rejected whole.
- INV-B3  with ``retractable`` given, a reinstate whose target the
          predicate refuses is rejected; the predicate sees only what the
          snapshot recorded (``seq``, and ``weight`` when given).
- INV-B4  the budget acts in ``check`` only: a log written under a
          budgeted reducer replays to the same snapshot under the
          unbudgeted default, and the version string is unchanged.
- INV-V1  ``view(k)`` carries no survivor list and its size is bounded
          by k and the number of obligations, not by log length.
- INV-V2  ``view(k)`` is a pure function of the snapshot and the last k
          envelopes; ``Session.view`` equals it.
- INV-W1  ``weight`` is recorded iff given and iff the envelope asserted
          something; it never changes what is eliminated; ``reason`` stays
          in the payload only.
"""

import json

import pytest

from cmbs import (
    InMemoryOpLogStore,
    MaskMeetTombstoneReducer,
    OperationSpec,
    ReinstatingMaskReducer,
    Session,
    reducer_for_version,
)


def v2(ids=("H1", "H2", "H3", "H4"), reducer=None, **kw) -> Session:
    return Session(
        hypothesis_ids=set(ids),
        reducer=reducer if reducer is not None else ReinstatingMaskReducer(),
        **kw,
    )


def probe(s: Session, pid: str, elim, **kw):
    return s.submit_probe_result(
        probe_id=pid, observable_id=f"obs:{pid}", eliminated=set(elim), **kw
    )


# =============================================================================
# Bounded view
# =============================================================================


class TestView:
    def _busy(self, n_probes: int = 3) -> Session:
        s = v2(ids=[f"H{i}" for i in range(10)])
        s.enter_obligation("N", 2)
        s.enter_obligation("G", 1, semantics="gross")
        for i in range(n_probes):
            probe(s, f"P{i}", {f"H{i}"})
        s.request_obligation_exit("G")
        s.reinstate_probe("P0")
        s.reinstate(99)  # rejected: out of range
        return s

    def test_view_shape_and_json(self):
        s = self._busy()
        v = s.view()
        assert json.loads(json.dumps(v)) == v
        assert set(v) == {
            "session_id",
            "seq",
            "state_hash",
            "position_digest",
            "n_survivors",
            "entropy",
            "terminated",
            "obligations",
            "closed_obligations",
            "n_in_force_pairs",
            "n_reinstated_pairs",
            "reinstate_count",
            "recent",
        }
        snap = s.snapshot()
        assert v["seq"] == snap.seq == s.head_seq
        assert v["state_hash"] == snap.state_hash
        assert v["position_digest"] == snap.position_digest
        assert v["n_survivors"] == 8
        assert v["entropy"] == snap.entropy
        assert v["terminated"] is False
        assert v["n_in_force_pairs"] == 2
        assert v["n_reinstated_pairs"] == 1
        assert v["reinstate_count"] == 1

    def test_inv_v1_no_survivor_list(self):
        v = self._busy().view()
        flat = json.dumps(v)
        assert "survivors" not in v and "eliminated" not in v
        assert "asserted_pairs" not in v and "weights" not in v
        assert '"H1"' not in flat and '"H5"' not in flat

    def test_inv_v1_size_does_not_grow_with_the_log(self):
        small = v2(ids=[f"H{i}" for i in range(200)])
        big = v2(ids=[f"H{i}" for i in range(200)])
        for i in range(6):
            probe(small, f"P{i}", {f"H{i}"})
        for i in range(150):
            probe(big, f"P{i}", {f"H{i}"})
        for s in (small, big):
            s.append(OperationSpec(op_type="note", payload={"i": 1}))
        a, b = json.dumps(small.view(k=5)), json.dumps(big.view(k=5))
        # Only digit widths may differ: seq and the counts grew from 1-2
        # digits to 3. Nothing per-hypothesis or per-envelope leaks in.
        assert abs(len(b) - len(a)) < 40, (len(a), len(b))
        assert big.view(k=5)["n_in_force_pairs"] == 150
        assert len(big.view(k=5)["recent"]) == len(small.view(k=5)["recent"]) == 5

    def test_obligations_carry_semantics_and_progress(self):
        s = self._busy()
        (entry,) = s.view()["obligations"]
        assert entry == {
            "obligation_id": "N",
            "semantics": "net",
            "min_eliminations": 2,
            "progress": 2,  # H1, H2 dead; H0 reinstated
        }
        (closed,) = s.view()["closed_obligations"]
        assert closed == {
            "obligation_id": "G",
            "open_seq": 2,
            "exit_seq": 6,
            "semantics": "gross",
            "min_eliminations": 1,
            "progress_at_exit": 3,
        }

    def test_recent_summarises_the_last_k_envelopes(self):
        s = self._busy()
        recent = s.view(k=3)["recent"]
        assert [r["seq"] for r in recent] == [6, 7, 8]
        assert [r["op_type"] for r in recent] == ["exit_obligation", "reinstate", "reinstate"]
        assert [r["accepted"] for r in recent] == [True, True, False]
        assert recent[2]["rejected_reason"].startswith("seq 99 out of range")
        assert recent[0]["rejected_reason"] is None
        assert set(recent[0]) == {"seq", "op_type", "accepted", "rejected_reason"}

    def test_k_edge_cases(self):
        s = self._busy()
        assert s.view(k=0)["recent"] == []
        assert len(s.view(k=100)["recent"]) == s.head_seq
        assert len(s.view(k=5)["recent"]) == 5
        fresh = v2()
        assert fresh.view()["recent"] == []
        assert fresh.view()["seq"] == 0
        for bad in (-1, 1.5, True):
            with pytest.raises((TypeError, ValueError)):
                s.view(k=bad)
            with pytest.raises((TypeError, ValueError)):
                s.snapshot().view(k=bad)

    def test_inv_v2_view_is_a_pure_function_of_snapshot_and_tail(self):
        s = self._busy()
        for k in (0, 1, 3, 5, 50):
            ops = s.operations()
            tail = ops[-k:] if k else ()
            assert s.view(k) == s.snapshot().view(k, recent=tail)
            # Passing the whole log is fine; only the last k are read.
            assert s.view(k) == s.snapshot().view(k, recent=ops)
        # And it is the same after recovery from the store.
        store = InMemoryOpLogStore()
        t = v2(store=store)
        probe(t, "P1", {"H1"})
        t.reinstate_probe("P1")
        assert Session.recover(store, t.session_id).view() == t.view()

    def test_view_under_v1_reducer(self):
        s = Session(hypothesis_ids={"H1", "H2"})
        probe(s, "P1", {"H1"})
        v = s.view()
        assert v["n_survivors"] == 1
        assert v["n_in_force_pairs"] == 0  # v1 keeps no pairs
        assert v["reinstate_count"] == 0
        assert v["recent"][0]["op_type"] == "probe_result"


# =============================================================================
# Reinstatement budget
# =============================================================================


class TestBudgetConstruction:
    def test_defaults_are_unlimited(self):
        r = ReinstatingMaskReducer()
        assert r.max_reinstates is None
        assert r.max_reinstated_pairs is None
        assert r.retractable is None
        assert r.budgeted is False

    def test_budget_does_not_change_the_version(self):
        r = ReinstatingMaskReducer(max_reinstates=1, max_reinstated_pairs=2, retractable=lambda p: True)
        assert r.version == ReinstatingMaskReducer.version == "v2_mask_reinstate"
        assert r.budgeted is True

    def test_registry_yields_the_unbudgeted_default(self):
        r = reducer_for_version("v2_mask_reinstate")
        assert isinstance(r, ReinstatingMaskReducer)
        assert r.budgeted is False

    def test_invalid_budget_parameters(self):
        with pytest.raises(ValueError):
            ReinstatingMaskReducer(max_reinstates=-1)
        with pytest.raises(ValueError):
            ReinstatingMaskReducer(max_reinstated_pairs=-1)
        with pytest.raises(TypeError):
            ReinstatingMaskReducer(max_reinstates=1.5)
        with pytest.raises(TypeError):
            ReinstatingMaskReducer(max_reinstates=True)
        with pytest.raises(TypeError):
            ReinstatingMaskReducer(retractable="yes")

    def test_zero_caps_forbid_all_reinstatement(self):
        for r in (
            ReinstatingMaskReducer(max_reinstates=0),
            ReinstatingMaskReducer(max_reinstated_pairs=0),
        ):
            s = v2(reducer=r)
            probe(s, "P1", {"H1"})
            res = s.reinstate_probe("P1")
            assert res.accepted is False
            assert "H1" not in s.survivors


class TestBudgetEnforcement:
    def test_inv_b1_total_reinstate_cap(self):
        s = v2(reducer=ReinstatingMaskReducer(max_reinstates=2))
        probe(s, "P1", {"H1"})
        probe(s, "P2", {"H2"})
        probe(s, "P3", {"H3"})
        assert s.reinstate_probe("P1").accepted is True
        assert s.reinstate_probe("P2").accepted is True
        before = s.snapshot()

        third = s.reinstate_probe("P3")

        assert third.accepted is False
        assert "reinstatement budget exhausted: 2 of 2" in third.error
        assert "H3" not in s.survivors
        after = s.snapshot()
        assert after.reinstate_count == 2
        assert after.reinstated_pairs == before.reinstated_pairs
        assert after.survivors == before.survivors

    def test_inv_b1_over_budget_attempt_is_logged_as_rejected(self):
        s = v2(reducer=ReinstatingMaskReducer(max_reinstates=1))
        probe(s, "P1", {"H1"})
        probe(s, "P2", {"H2"})
        s.reinstate_probe("P1")
        head_before = s.head_seq

        s.reinstate_probe("P2")

        assert s.head_seq == head_before + 1
        last = s.operations()[-1]
        assert last.op_type == "reinstate"
        assert last.accepted is False
        assert "reinstatement budget exhausted" in last.rejected_reason
        assert last.payload == {"probe_id": "P2"}
        # And the view reports it like any other rejection.
        assert s.view(k=1)["recent"][0]["accepted"] is False
        assert s.view()["reinstate_count"] == 1

    def test_inv_b1_rejected_reinstates_do_not_consume_budget(self):
        s = v2(reducer=ReinstatingMaskReducer(max_reinstates=1))
        probe(s, "P1", {"H1"})
        assert s.reinstate(99).accepted is False  # invalid, not budget
        assert s.snapshot().reinstate_count == 0
        assert s.reinstate_probe("P1").accepted is True
        assert s.snapshot().reinstate_count == 1

    def test_inv_b2_pair_cap_counts_pairs_not_ops(self):
        s = v2(reducer=ReinstatingMaskReducer(max_reinstated_pairs=2))
        probe(s, "P1", {"H1", "H2", "H3"})
        probe(s, "P2", {"H4"})

        whole = s.reinstate_probe("P1")  # 3 pairs > cap
        assert whole.accepted is False
        assert "reinstated-pair cap exceeded" in whole.error
        assert "bring the total to 3, cap is 2" in whole.error
        assert s.survivors == frozenset()  # rejected whole: nothing voided

        assert s.reinstate(1, hypotheses={"H1"}).accepted is True
        assert s.reinstate_probe("P2").accepted is True  # total 2 == cap
        third = s.reinstate(1, hypotheses={"H2"})
        assert third.accepted is False
        assert "bring the total to 3, cap is 2" in third.error
        assert s.survivors == {"H1", "H4"}
        assert len(s.snapshot().reinstated_pairs) == 2
        assert s.snapshot().reinstate_count == 2

    def test_inv_b2_re_killing_a_reinstated_hypothesis_does_not_free_budget(self):
        # The record set is monotone: a reinstated pair stays reinstated
        # even if the hypothesis is later eliminated again.
        s = v2(reducer=ReinstatingMaskReducer(max_reinstated_pairs=1))
        probe(s, "P1", {"H1"})
        assert s.reinstate_probe("P1").accepted is True
        probe(s, "P2", {"H1"})
        assert s.reinstate_probe("P2").accepted is False

    def test_both_caps_apply_and_the_first_breached_names_the_reason(self):
        s = v2(reducer=ReinstatingMaskReducer(max_reinstates=1, max_reinstated_pairs=1))
        probe(s, "P1", {"H1", "H2"})
        probe(s, "P2", {"H3"})
        r = s.reinstate_probe("P1")
        assert r.accepted is False and "reinstated-pair cap" in r.error
        assert s.reinstate_probe("P2").accepted is True
        r = s.reinstate(1, hypotheses={"H1"})
        assert r.accepted is False and "reinstatement budget exhausted" in r.error


class TestRetractablePredicate:
    def test_inv_b3_predicate_sees_the_recorded_weight(self):
        seen = []

        def only_light(recorded):
            seen.append(dict(recorded))
            return recorded.get("weight", 0.0) < 0.5

        s = v2(reducer=ReinstatingMaskReducer(retractable=only_light))
        probe(s, "P1", {"H1"}, weight=0.2)
        probe(s, "P2", {"H2"}, weight=0.9)
        probe(s, "P3", {"H3"})  # no weight

        assert s.reinstate_probe("P1").accepted is True
        heavy = s.reinstate_probe("P2")
        assert heavy.accepted is False
        assert "not retractable under the reducer's predicate" in heavy.error
        assert "weight 0.9" in heavy.error
        assert "H2" not in s.survivors
        assert s.reinstate_probe("P3").accepted is True  # predicate treats missing as 0.0

        assert seen == [{"seq": 1, "weight": 0.2}, {"seq": 2, "weight": 0.9}, {"seq": 3}]

    def test_inv_b3_predicate_may_refuse_unweighted_targets(self):
        s = v2(reducer=ReinstatingMaskReducer(retractable=lambda p: "weight" in p))
        probe(s, "P1", {"H1"})
        r = s.reinstate_probe("P1")
        assert r.accepted is False
        assert "(no weight)" in r.error
        last = s.operations()[-1]
        assert last.accepted is False and last.op_type == "reinstate"

    def test_inv_b3_predicate_runs_after_target_validation(self):
        calls = []
        s = v2(reducer=ReinstatingMaskReducer(retractable=lambda p: calls.append(p) or True))
        probe(s, "P1", {"H1"})
        assert s.reinstate(99).accepted is False  # invalid target: predicate not consulted
        assert calls == []
        assert s.reinstate_probe("P1").accepted is True
        assert calls == [{"seq": 1}]

    def test_predicate_sees_a_seq_so_age_policies_are_expressible(self):
        s = v2(reducer=ReinstatingMaskReducer(retractable=lambda p: p["seq"] >= 2))
        probe(s, "P1", {"H1"})
        probe(s, "P2", {"H2"})
        assert s.reinstate_probe("P1").accepted is False
        assert s.reinstate_probe("P2").accepted is True

    def test_predicate_exception_propagates_and_logs_nothing(self):
        def boom(_):
            raise RuntimeError("policy bug")

        s = v2(reducer=ReinstatingMaskReducer(retractable=boom))
        probe(s, "P1", {"H1"})
        head = s.head_seq
        with pytest.raises(RuntimeError, match="policy bug"):
            s.reinstate_probe("P1")
        assert s.head_seq == head


class TestBudgetReplayAndRecovery:
    def _budgeted_log(self, store):
        s = v2(
            store=store,
            reducer=ReinstatingMaskReducer(
                max_reinstates=1, max_reinstated_pairs=5, retractable=lambda p: True
            ),
        )
        probe(s, "P1", {"H1"}, weight=0.3)
        probe(s, "P2", {"H2"})
        s.reinstate_probe("P1")
        s.reinstate_probe("P2")  # rejected: budget
        return s

    def test_inv_b4_budgeted_log_replays_identically_under_the_default(self):
        s = self._budgeted_log(InMemoryOpLogStore())
        replayed = ReinstatingMaskReducer().reduce(
            s.initial_hypotheses, s.operations(), session_id=s.session_id
        )
        assert replayed == s.snapshot()
        assert replayed.reinstate_count == 1

    def test_inv_b4_recovery_through_the_registry_drops_the_budget(self):
        store = InMemoryOpLogStore()
        s = self._budgeted_log(store)
        r = Session.recover(store, s.session_id)
        assert r.snapshot() == s.snapshot()
        assert r.reducer.budgeted is False
        # Without the budget, the recovered session accepts what the
        # original refused: the limit was never part of the log.
        assert r.reinstate_probe("P2").accepted is True

    def test_inv_b4_recovery_with_an_explicit_budgeted_reducer_keeps_it(self):
        store = InMemoryOpLogStore()
        s = self._budgeted_log(store)
        r = Session.recover(store, s.session_id, reducer=ReinstatingMaskReducer(max_reinstates=1))
        assert r.snapshot() == s.snapshot()
        again = r.reinstate_probe("P2")
        assert again.accepted is False
        assert "reinstatement budget exhausted" in again.error

    def test_budget_fields_are_in_the_hash_only_when_populated(self):
        a = v2(session_id="s")
        b = v2(session_id="s")
        probe(a, "P1", {"H1"})
        probe(b, "P1", {"H1"}, weight=0.5)
        assert a.snapshot().state_hash != b.snapshot().state_hash
        assert a.survivors == b.survivors
        a.reinstate_probe("P1")
        b.reinstate_probe("P1")
        assert a.snapshot().reinstate_count == b.snapshot().reinstate_count == 1


# =============================================================================
# weight / reason on eliminations
# =============================================================================


class TestWeightAndReason:
    def test_inv_w1_weight_and_reason_are_copied_into_the_payload(self):
        s = v2()
        probe(s, "P1", {"H1"}, weight=0.75, reason="flaky sensor")
        env = s.operations()[-1]
        assert env.payload["weight"] == 0.75
        assert env.payload["reason"] == "flaky sensor"
        assert s.snapshot().weights == {1: 0.75}
        assert s.survivors == {"H2", "H3", "H4"}

    def test_inv_w1_omitted_keys_are_absent(self):
        s = v2()
        probe(s, "P1", {"H1"})
        assert "weight" not in s.operations()[-1].payload
        assert "reason" not in s.operations()[-1].payload
        assert s.snapshot().weights == {}

    def test_inv_w1_weight_never_changes_what_is_eliminated(self):
        a, b = v2(session_id="s"), v2(session_id="s")
        probe(a, "P1", {"H1", "H2"})
        probe(b, "P1", {"H1", "H2"}, weight=100.0, reason="x")
        assert a.survivors == b.survivors
        assert a.snapshot().asserted_pairs == b.snapshot().asserted_pairs
        assert a.obligation_progress("none") is None
        # Reinstating works the same with or without a weight, absent a budget.
        assert a.reinstate_probe("P1").revived == b.reinstate_probe("P1").revived

    def test_inv_w1_reason_is_not_recorded_on_the_snapshot(self):
        s = v2()
        probe(s, "P1", {"H1"}, reason="because")
        d = s.snapshot().to_dict()
        assert "because" not in json.dumps(d)
        assert d["weights"] == []

    def test_weights_only_for_envelopes_that_asserted_something(self):
        s = v2()
        probe(s, "P1", set(), weight=0.4)  # asserted nothing
        probe(s, "P2", {"NOPE"}, weight=0.4)  # outside the universe
        s.append(
            OperationSpec(
                op_type="refine",
                payload={"if_attr": "c", "equals": "x", "eliminate": ["H1"], "weight": 0.4},
            )
        )  # condition false
        assert s.snapshot().weights == {}
        s.append(
            OperationSpec(op_type="assert", payload={"eliminate": ["H1"], "weight": 2})
        )
        assert s.snapshot().weights == {4: 2.0}
        assert isinstance(s.snapshot().weights[4], float)
        assert set(s.snapshot().weights) <= {q for q, _ in s.snapshot().asserted_pairs}

    def test_weight_on_a_rejected_elimination_is_not_recorded(self):
        s = v2()
        probe(s, "P1", {"H1"})
        probe(s, "P1", {"H2"}, weight=0.9)  # duplicate probe_id: rejected
        assert s.snapshot().weights == {}

    def test_malformed_weight_or_reason_rejected_under_v2(self):
        s = v2()
        for payload in (
            {"eliminate": ["H1"], "weight": "heavy"},
            {"eliminate": ["H1"], "weight": True},
            {"eliminate": ["H1"], "weight": None},
            {"eliminate": ["H1"], "reason": 42},
        ):
            r = s.append(OperationSpec(op_type="probe_result", payload=payload))
            assert r.envelope.accepted is False, payload
            assert "when given" in r.envelope.rejected_reason
        assert s.survivors == {"H1", "H2", "H3", "H4"}
        assert s.snapshot().weights == {}

    def test_v1_stores_but_never_reads_weight_or_reason(self):
        s = Session(hypothesis_ids={"H1", "H2"}, reducer=MaskMeetTombstoneReducer())
        r = probe(s, "P1", {"H1"}, weight="anything", reason="opaque")
        assert r.accepted is True
        assert s.operations()[-1].payload["weight"] == "anything"
        assert s.snapshot().weights == {}
        assert s.snapshot().reinstate_count == 0

    def test_weights_round_trip_to_dict_and_survive_recovery(self):
        store = InMemoryOpLogStore()
        s = v2(store=store)
        probe(s, "P1", {"H1"}, weight=0.1)
        probe(s, "P2", {"H2"}, weight=0.2)
        d = s.snapshot().to_dict()
        assert json.loads(json.dumps(d)) == d
        assert d["weights"] == [[1, 0.1], [2, 0.2]]
        assert d["reinstate_count"] == 0
        assert Session.recover(store, s.session_id).snapshot().weights == {1: 0.1, 2: 0.2}
