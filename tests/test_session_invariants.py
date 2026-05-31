"""
Invariant test suite for the unified ``Session`` kernel.

Ported from ``tests/test_v0_core.py``. Same 49 tests against the new
public surface decided in ADR-002. All will be red until the kernel
implementation lands.
"""

import math

import pytest

from cmbs.session import Session
from cmbs.store import InMemoryOpLogStore

# =============================================================================
# 1. INVARIANT TESTS
# =============================================================================


# -----------------------------------------------------------------------------
# 1.1 INV-3: Probe Non-Repetition
# -----------------------------------------------------------------------------


class TestINV3ProbeNonRepetition:
    """INV-3: A probe executed within an obligation scope may not be re-executed."""

    def test_inv3_01_unique_probes_accepted(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3"})

        r1 = session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated=set())
        r2 = session.submit_probe_result(probe_id="P2", observable_id="O2", eliminated=set())
        r3 = session.submit_probe_result(probe_id="P3", observable_id="O3", eliminated=set())

        assert r1.accepted is True
        assert r2.accepted is True
        assert r3.accepted is True

    def test_inv3_02_duplicate_probe_rejected(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3"})
        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated=set())

        result = session.submit_probe_result(probe_id="P1", observable_id="O2", eliminated=set())

        assert result.accepted is False

    def test_inv3_03_probe_uniqueness_is_per_id_not_per_content(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3"})

        r1 = session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        r2 = session.submit_probe_result(probe_id="P2", observable_id="O1", eliminated={"H2"})

        assert r1.accepted is True
        assert r2.accepted is True

    def test_inv3_04_probe_rejection_does_not_affect_hypothesis_state(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3"})
        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})

        result = session.submit_probe_result(probe_id="P1", observable_id="O2", eliminated={"H2"})

        assert result.accepted is False
        assert session.survivors == {"H2", "H3"}

    def test_inv3_05_probe_ids_are_order_independent_for_uniqueness(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3", "H4"})

        r3 = session.submit_probe_result(probe_id="P3", observable_id="O1", eliminated=set())
        r1 = session.submit_probe_result(probe_id="P1", observable_id="O2", eliminated=set())
        r4 = session.submit_probe_result(probe_id="P4", observable_id="O3", eliminated=set())
        r2 = session.submit_probe_result(probe_id="P2", observable_id="O4", eliminated=set())

        assert r3.accepted is True
        assert r1.accepted is True
        assert r4.accepted is True
        assert r2.accepted is True


# -----------------------------------------------------------------------------
# 1.2 INV-5a: Entropy Quantification
# -----------------------------------------------------------------------------


class TestINV5aEntropyQuantification:
    """INV-5a: Belief uncertainty must be computable as a scalar at each step."""

    def test_inv5a_01_initial_entropy_matches_hypothesis_count(self):
        n = 8
        session = Session(hypothesis_ids={f"H{i}" for i in range(1, n + 1)})
        assert session.entropy == pytest.approx(math.log2(n))

    def test_inv5a_02_entropy_decreases_after_elimination(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3", "H4"})
        assert session.entropy == pytest.approx(2.0)

        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})

        assert session.entropy == pytest.approx(math.log2(3))

    def test_inv5a_03_entropy_is_zero_with_singleton_survivor(self):
        session = Session(hypothesis_ids={"H1", "H2"})
        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        assert session.entropy == pytest.approx(0.0)

    def test_inv5a_04_entropy_unchanged_when_no_elimination_occurs(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3"})
        initial_entropy = session.entropy

        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated=set())

        assert session.entropy == pytest.approx(initial_entropy)
        assert session.entropy == pytest.approx(math.log2(3))

    def test_inv5a_05_entropy_is_monotonically_non_increasing(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3", "H4", "H5"})
        entropy_trace = [session.entropy]

        for i, h in enumerate(["H1", "H2", "H3", "H4"]):
            session.submit_probe_result(
                probe_id=f"P{i+1}", observable_id=f"O{i+1}", eliminated={h}
            )
            entropy_trace.append(session.entropy)

        for j in range(len(entropy_trace) - 1):
            assert entropy_trace[j + 1] <= entropy_trace[j]


# -----------------------------------------------------------------------------
# 1.3 INV-6: Non-Trivial Exit
# -----------------------------------------------------------------------------


class TestINV6NonTrivialExit:
    """INV-6: An epistemic obligation may only be exited if belief has measurably changed."""

    def test_inv6_01_obligation_exit_permitted_after_elimination(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3"})
        session.enter_obligation(obligation_id="O1", min_eliminations=1)

        session.submit_probe_result(probe_id="P1", observable_id="O_obs", eliminated={"H1"})
        result = session.request_obligation_exit(obligation_id="O1")

        assert result.permitted is True

    def test_inv6_02_obligation_exit_rejected_with_zero_eliminations(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3"})
        session.enter_obligation(obligation_id="O1", min_eliminations=1)

        result = session.request_obligation_exit(obligation_id="O1")

        assert result.permitted is False

    def test_inv6_03_obligation_exit_respects_threshold(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3", "H4", "H5"})
        session.enter_obligation(obligation_id="O1", min_eliminations=3)

        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        session.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={"H2"})
        result = session.request_obligation_exit(obligation_id="O1")

        assert result.permitted is False

    def test_inv6_04_obligation_exit_permitted_at_threshold(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3", "H4"})
        session.enter_obligation(obligation_id="O1", min_eliminations=2)

        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        session.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={"H2"})
        result = session.request_obligation_exit(obligation_id="O1")

        assert result.permitted is True

    def test_inv6_05_eliminations_outside_obligation_dont_count(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3", "H4"})

        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        session.enter_obligation(obligation_id="O1", min_eliminations=1)
        result = session.request_obligation_exit(obligation_id="O1")

        assert result.permitted is False

    def test_inv6_06_multiple_obligations_track_independently(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3", "H4", "H5"})

        session.enter_obligation(obligation_id="O1", min_eliminations=2)
        session.submit_probe_result(probe_id="P1", observable_id="obs1", eliminated={"H1"})
        session.enter_obligation(obligation_id="O2", min_eliminations=1)
        session.submit_probe_result(probe_id="P2", observable_id="obs2", eliminated={"H2"})

        result_o2 = session.request_obligation_exit(obligation_id="O2")
        result_o1 = session.request_obligation_exit(obligation_id="O1")

        assert result_o2.permitted is True
        assert result_o1.permitted is True


# =============================================================================
# 2. BOUNDARY / NON-LEAKAGE TESTS
# =============================================================================


class TestBoundaryOpaqueIdentifiers:
    """Kernel must not interpret identifier content."""

    def test_bnd_01_hypothesis_ids_are_opaque(self):
        hypothesis_ids = {"uuid-1234-5678", "numeric_99", "🔬", "", "with spaces", "UPPERCASE"}
        session = Session(hypothesis_ids=hypothesis_ids)

        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"🔬"})
        session.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={""})

        assert session.survivors == {"uuid-1234-5678", "numeric_99", "with spaces", "UPPERCASE"}

    def test_bnd_02_probe_ids_are_opaque(self):
        session = Session(hypothesis_ids={"H1", "H2"})

        r1 = session.submit_probe_result(probe_id="probe-alpha", observable_id="O1", eliminated=set())
        r2 = session.submit_probe_result(probe_id="12345", observable_id="O2", eliminated=set())
        r3 = session.submit_probe_result(probe_id="émoji🎯", observable_id="O3", eliminated=set())
        r4 = session.submit_probe_result(probe_id="", observable_id="O4", eliminated=set())

        assert r1.accepted is True
        assert r2.accepted is True
        assert r3.accepted is True
        assert r4.accepted is True

    def test_bnd_03_observable_ids_are_opaque(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3"})

        result = session.submit_probe_result(
            probe_id="P1", observable_id="anything_at_all_here", eliminated={"H1"}
        )

        assert result.accepted is True
        assert session.survivors == {"H2", "H3"}

    def test_bnd_04_conclusion_ids_are_opaque(self):
        session = Session(hypothesis_ids={"H1", "H2"}, stability_window=3)

        session.declare_conclusion(conclusion_id="conclusion_X")
        session.declare_conclusion(conclusion_id="42")
        session.declare_conclusion(conclusion_id="true")
        session.declare_conclusion(conclusion_id="compliant")
        session.declare_conclusion(conclusion_id="unknown")
        # No assertion on specific behavior, just that no error occurs

    def test_bnd_05_ids_that_look_like_domain_concepts_are_not_special_cased(self):
        session = Session(hypothesis_ids={"compliant", "non_compliant", "error"})

        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"compliant"})

        assert session.survivors == {"non_compliant", "error"}
        assert session.entropy == pytest.approx(math.log2(2))


class TestBoundaryNonSingletonTermination:
    """Termination must not assume singleton survivor."""

    def test_bnd_06_termination_permitted_with_multiple_survivors(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3"}, stability_window=2)

        session.declare_conclusion(conclusion_id="C1")
        session.declare_conclusion(conclusion_id="C1")
        result = session.request_termination()

        assert result.permitted is True

    def test_bnd_07_termination_permitted_with_zero_survivors(self):
        session = Session(hypothesis_ids={"H1"}, stability_window=2)

        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        session.declare_conclusion(conclusion_id="C1")
        session.declare_conclusion(conclusion_id="C1")
        result = session.request_termination()

        assert result.permitted is True


class TestBoundaryNonBinaryConclusion:
    """Conclusions must not be assumed binary."""

    def test_bnd_08_more_than_two_distinct_conclusions_supported(self):
        session = Session(hypothesis_ids={"H1", "H2"}, stability_window=3)

        for c in ("C1", "C2", "C3", "C4", "C5"):
            session.declare_conclusion(conclusion_id=c)
        # No error should occur

    def test_bnd_09_conclusion_stability_works_for_any_conclusion_value(self):
        s1 = Session(hypothesis_ids={"H1", "H2"}, stability_window=3)
        for _ in range(3):
            s1.declare_conclusion(conclusion_id="C1")
        assert s1.request_termination().permitted is True

        s2 = Session(hypothesis_ids={"H1", "H2"}, stability_window=3)
        for _ in range(3):
            s2.declare_conclusion(conclusion_id="C99")
        assert s2.request_termination().permitted is True


class TestBoundaryNonExecutionSemantics:
    """Kernel must not assume execution model."""

    def test_bnd_10_no_attempt_or_success_states_exist(self):
        forbidden_terms = {"attempted", "successful", "failed", "pending", "executing", "running"}
        for member in dir(Session):
            member_lower = member.lower()
            for term in forbidden_terms:
                assert term not in member_lower, f"Session contains execution-model term: {member}"

    def test_bnd_11_probe_results_are_observations_not_executions(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3"})

        assert hasattr(session, "submit_probe_result")
        assert not hasattr(session, "execute_probe")
        assert not hasattr(session, "run_probe")

        result = session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        assert result.accepted is True

    def test_bnd_12_kernel_has_no_probe_scheduling_capability(self):
        scheduling_methods = [
            "execute_probe",
            "run_probe",
            "schedule_probe",
            "select_next_probe",
            "get_next_probe",
            "recommend_probe",
        ]
        for method in scheduling_methods:
            assert not hasattr(Session, method), f"Session should not have method: {method}"


# =============================================================================
# 3. OBLIGATION & TERMINATION TESTS
# =============================================================================


class TestObligationDiscipline:
    """Obligation lifecycle and scoping."""

    def test_obl_01_obligation_entry_is_adapter_initiated(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3"})
        session.enter_obligation(obligation_id="O1", min_eliminations=1)
        assert "O1" in session.active_obligations

    def test_obl_02_obligation_cannot_self_trigger(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3"})

        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        session.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={"H2"})

        assert session.active_obligations == frozenset()

    def test_obl_03_obligation_parameters_are_adapter_provided(self):
        session = Session(hypothesis_ids={f"H{i}" for i in range(1, 11)})
        session.enter_obligation(obligation_id="O1", min_eliminations=5)

        for i in range(1, 5):
            session.submit_probe_result(
                probe_id=f"P{i}", observable_id=f"O{i}", eliminated={f"H{i}"}
            )

        assert session.request_obligation_exit(obligation_id="O1").permitted is False

        session.submit_probe_result(probe_id="P5", observable_id="O5", eliminated={"H5"})
        assert session.request_obligation_exit(obligation_id="O1").permitted is True

    def test_obl_04_nested_obligations_are_independent(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3", "H4", "H5"})

        session.enter_obligation(obligation_id="O1", min_eliminations=2)
        session.submit_probe_result(probe_id="P1", observable_id="obs1", eliminated={"H1"})
        session.enter_obligation(obligation_id="O2", min_eliminations=1)
        session.submit_probe_result(probe_id="P2", observable_id="obs2", eliminated={"H2"})

        assert session.request_obligation_exit(obligation_id="O2").permitted is True
        assert session.request_obligation_exit(obligation_id="O1").permitted is True

    def test_obl_05_exiting_non_existent_obligation_fails_gracefully(self):
        session = Session(hypothesis_ids={"H1", "H2"})

        result = session.request_obligation_exit(obligation_id="O_nonexistent")

        assert result.permitted is False or result.error is not None


class TestEntropyObservation:
    """Entropy is observable but does not gate operations."""

    def test_ent_01_entropy_is_queryable_at_any_time(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3", "H4"})

        e1 = session.entropy
        assert e1 is not None
        assert e1 == pytest.approx(2.0)

        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        e2 = session.entropy
        assert e2 is not None
        assert e2 == pytest.approx(math.log2(3))

        session.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={"H2"})
        e3 = session.entropy
        assert e3 is not None
        assert e3 == pytest.approx(1.0)

    def test_ent_02_entropy_does_not_gate_termination(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3", "H4"}, stability_window=2)

        session.declare_conclusion(conclusion_id="C1")
        session.declare_conclusion(conclusion_id="C1")

        assert session.entropy == pytest.approx(2.0)

        assert session.request_termination().permitted is True

    def test_ent_03_entropy_does_not_gate_obligation_exit(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3", "H4", "H5"})
        session.enter_obligation(obligation_id="O1", min_eliminations=1)

        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})

        assert session.entropy == pytest.approx(2.0)

        assert session.request_obligation_exit(obligation_id="O1").permitted is True

    def test_ent_04_zero_entropy_does_not_auto_terminate(self):
        session = Session(hypothesis_ids={"H1", "H2"}, stability_window=2)

        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})

        assert session.entropy == pytest.approx(0.0)
        assert session.is_terminated is False


class TestTerminationDiscipline:
    """Termination lifecycle and stability."""

    def test_term_01_termination_requires_explicit_adapter_request(self):
        session = Session(hypothesis_ids={"H1", "H2"}, stability_window=2)

        session.declare_conclusion(conclusion_id="C1")
        session.declare_conclusion(conclusion_id="C1")

        assert session.is_terminated is False

    def test_term_02_termination_rejected_if_conclusion_unstable(self):
        session = Session(hypothesis_ids={"H1", "H2"}, stability_window=3)

        session.declare_conclusion(conclusion_id="C1")
        session.declare_conclusion(conclusion_id="C2")
        assert session.request_termination().permitted is False

    def test_term_03_termination_permitted_after_stability_achieved(self):
        session = Session(hypothesis_ids={"H1", "H2"}, stability_window=3)

        for _ in range(3):
            session.declare_conclusion(conclusion_id="C1")
        assert session.request_termination().permitted is True

    def test_term_04_stability_resets_on_conclusion_change(self):
        session = Session(hypothesis_ids={"H1", "H2"}, stability_window=3)

        session.declare_conclusion(conclusion_id="C1")
        session.declare_conclusion(conclusion_id="C1")
        session.declare_conclusion(conclusion_id="C2")
        assert session.request_termination().permitted is False

    def test_term_05_termination_with_stability_disabled(self):
        session = Session(hypothesis_ids={"H1", "H2"}, stability_window=0)

        session.declare_conclusion(conclusion_id="C1")
        assert session.request_termination().permitted is True

    def test_term_06_termination_independent_of_obligation_state(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3"}, stability_window=3)

        session.enter_obligation(obligation_id="O1", min_eliminations=1)
        for _ in range(3):
            session.declare_conclusion(conclusion_id="C1")

        assert "O1" in session.active_obligations
        assert session.request_termination().permitted is True


# =============================================================================
# 4. MIGRATION / INCREMENTAL ADOPTION TESTS
# =============================================================================


class TestMigrationLegacyCompatibility:
    """Legacy ID formats and incremental elimination."""

    def test_mig_01_kernel_accepts_legacy_format_ids(self):
        legacy_hypothesis_ids = {"LEGACY_HYP_001", "LEGACY_HYP_002", "LEGACY_HYP_003"}
        session = Session(hypothesis_ids=legacy_hypothesis_ids)

        result = session.submit_probe_result(
            probe_id="LEGACY_PROBE_001",
            observable_id="LEGACY_OBS_001",
            eliminated={"LEGACY_HYP_001"},
        )

        assert result.accepted is True
        assert session.survivors == {"LEGACY_HYP_002", "LEGACY_HYP_003"}

    def test_mig_02_kernel_operates_with_partial_hypothesis_elimination(self):
        hypothesis_ids = {f"H{i}" for i in range(1, 101)}
        session = Session(hypothesis_ids=hypothesis_ids)

        for i in range(1, 6):
            session.submit_probe_result(
                probe_id=f"P{i}", observable_id=f"O{i}", eliminated={f"H{i}"}
            )

        assert len(session.survivors) == 95
        assert session.entropy == pytest.approx(math.log2(95))

    def test_mig_03_session_state_recovers_from_store(self):
        """Replacement for v0's serialize/deserialize test.

        In the unified model, state is recovered by replaying the op log
        from the store under the same reducer. This is the persistence
        story.
        """
        store = InMemoryOpLogStore()
        session = Session(
            hypothesis_ids={"H1", "H2", "H3", "H4"},
            stability_window=2,
            store=store,
        )
        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        session.enter_obligation(obligation_id="O1", min_eliminations=1)

        recovered = Session.recover(store=store, session_id=session.session_id)

        assert recovered.survivors == session.survivors
        assert recovered.entropy == pytest.approx(session.entropy)
        assert recovered.consumed_probes == session.consumed_probes
        assert recovered.active_obligations == session.active_obligations

    def test_mig_04_adapter_can_replay_historical_eliminations(self):
        session = Session(hypothesis_ids={"H1", "H2", "H3", "H4", "H5"})

        historical_events = [
            ("P1", "O1", {"H1"}),
            ("P2", "O2", {"H3"}),
            ("P3", "O3", {"H5"}),
        ]
        for probe_id, observable_id, eliminated in historical_events:
            session.submit_probe_result(
                probe_id=probe_id, observable_id=observable_id, eliminated=eliminated
            )

        assert session.survivors == {"H2", "H4"}
        assert session.entropy == pytest.approx(math.log2(2))


class TestMigrationIncrementalAdoption:
    """Running alongside legacy systems; audit trail."""

    def test_mig_05_kernel_can_run_alongside_legacy_system(self):
        hypothesis_ids = {"H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8"}
        session = Session(hypothesis_ids=hypothesis_ids)

        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1", "H2"})
        session.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={"H5"})

        legacy_survivor_count = 5
        legacy_entropy = math.log2(legacy_survivor_count)

        assert session.entropy == pytest.approx(legacy_entropy)

    def test_mig_06_kernel_provides_audit_trail_for_comparison(self):
        """In the unified model the audit trail is the op log itself.

        Filter envelopes to ``op_type == "probe_result"`` and read fields
        from ``payload`` to recover the v0 audit shape.
        """
        session = Session(hypothesis_ids={"H1", "H2", "H3", "H4"})

        session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        session.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={"H3"})

        ops = session.operations()
        probe_ops = [op for op in ops if op.op_type == "probe_result" and op.accepted]

        assert len(probe_ops) == 2
        assert probe_ops[0].idempotency_key == "P1"
        assert probe_ops[0].payload["observable_id"] == "O1"
        assert set(probe_ops[0].payload["eliminate"]) == {"H1"}
        assert probe_ops[1].idempotency_key == "P2"
        assert probe_ops[1].payload["observable_id"] == "O2"
        assert set(probe_ops[1].payload["eliminate"]) == {"H3"}
