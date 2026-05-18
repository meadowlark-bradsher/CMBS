"""
CMBS v0 Core Test Suite

Generated from: docs-vault/v0-test-specification.md
Date: 2026-02-02

All tests use opaque identifiers and avoid domain semantics.
Assumes core API exists and is implemented.
"""

import math

import pytest

# Core API assumed to exist (not yet implemented)
from cmbs.core import CMBSCore

# =============================================================================
# 1. INVARIANT TESTS
# =============================================================================


# -----------------------------------------------------------------------------
# 1.1 INV-3: Probe Non-Repetition
# -----------------------------------------------------------------------------


class TestINV3ProbeNonRepetition:
    """INV-3: A probe executed within an obligation scope may not be re-executed."""

    def test_inv3_01_unique_probes_accepted(self):
        """T-INV3-01: Unique probes accepted (Positive)

        Setup: Empty core with hypothesis set {H1, H2, H3}
        Action: Submit probe results with distinct probe IDs: P1, P2, P3
        Assert: All three submissions are accepted
        Protects: INV-3 — core accepts unique probes
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3"})

        result_p1 = core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated=set())
        result_p2 = core.submit_probe_result(probe_id="P2", observable_id="O2", eliminated=set())
        result_p3 = core.submit_probe_result(probe_id="P3", observable_id="O3", eliminated=set())

        assert result_p1.accepted is True
        assert result_p2.accepted is True
        assert result_p3.accepted is True

    def test_inv3_02_duplicate_probe_rejected(self):
        """T-INV3-02: Duplicate probe rejected (Negative)

        Setup: Core with hypothesis set {H1, H2, H3}; P1 already consumed
        Action: Submit probe result with probe ID P1 (duplicate)
        Assert: Submission is rejected
        Protects: INV-3 — core rejects duplicate probes
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3"})
        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated=set())

        result = core.submit_probe_result(probe_id="P1", observable_id="O2", eliminated=set())

        assert result.accepted is False

    def test_inv3_03_probe_uniqueness_is_per_id_not_per_content(self):
        """T-INV3-03: Probe uniqueness is per-ID, not per-content (Positive)

        Setup: Empty core with hypothesis set {H1, H2, H3}
        Action: Submit two probe results:
            - P1 with observable O1, eliminating {H1}
            - P2 with observable O1, eliminating {H2}
            (Same observable, different probe IDs)
        Assert: Both submissions are accepted
        Protects: INV-3 — uniqueness is determined by probe ID, not observable content
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3"})

        result_p1 = core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        result_p2 = core.submit_probe_result(probe_id="P2", observable_id="O1", eliminated={"H2"})

        assert result_p1.accepted is True
        assert result_p2.accepted is True

    def test_inv3_04_probe_rejection_does_not_affect_hypothesis_state(self):
        """T-INV3-04: Probe rejection does not affect hypothesis state (Negative)

        Setup: Core with hypothesis set {H1, H2, H3}; P1 already consumed, eliminated {H1}
        Action: Submit duplicate P1, claiming to eliminate {H2}
        Assert:
            - Submission is rejected
            - Survivor set remains {H2, H3} (not {H3})
        Protects: INV-3 — rejected probes have no side effects
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3"})
        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})

        result = core.submit_probe_result(probe_id="P1", observable_id="O2", eliminated={"H2"})

        assert result.accepted is False
        assert core.survivors == {"H2", "H3"}

    def test_inv3_05_probe_ids_are_order_independent_for_uniqueness(self):
        """T-INV3-05: Probe IDs are order-independent for uniqueness

        Setup: Empty core with hypothesis set {H1, H2, H3, H4}
        Action: Submit probes in order: P3, P1, P4, P2 (non-sequential)
        Assert: All four are accepted
        Protects: INV-3 — no ordering assumption on probe IDs
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3", "H4"})

        result_p3 = core.submit_probe_result(probe_id="P3", observable_id="O1", eliminated=set())
        result_p1 = core.submit_probe_result(probe_id="P1", observable_id="O2", eliminated=set())
        result_p4 = core.submit_probe_result(probe_id="P4", observable_id="O3", eliminated=set())
        result_p2 = core.submit_probe_result(probe_id="P2", observable_id="O4", eliminated=set())

        assert result_p3.accepted is True
        assert result_p1.accepted is True
        assert result_p4.accepted is True
        assert result_p2.accepted is True


# -----------------------------------------------------------------------------
# 1.2 INV-5a: Entropy Quantification
# -----------------------------------------------------------------------------


class TestINV5aEntropyQuantification:
    """INV-5a: Belief uncertainty must be computable as a scalar at each step."""

    def test_inv5a_01_initial_entropy_matches_hypothesis_count(self):
        """T-INV5A-01: Initial entropy matches hypothesis count (Positive)

        Setup: Core initialized with hypothesis set of size N
        Action: Query entropy before any eliminations
        Assert: Entropy equals log2(N)
        Protects: INV-5a — entropy reflects survivor count
        """
        n = 8
        hypothesis_ids = {f"H{i}" for i in range(1, n + 1)}
        core = CMBSCore(hypothesis_ids=hypothesis_ids)

        assert core.entropy == pytest.approx(math.log2(n))

    def test_inv5a_02_entropy_decreases_after_elimination(self):
        """T-INV5A-02: Entropy decreases after elimination (Positive)

        Setup: Core with hypothesis set {H1, H2, H3, H4} (entropy = 2.0)
        Action: Submit probe eliminating {H1}
        Assert: Entropy equals log2(3) ≈ 1.585
        Protects: INV-5a — entropy updates on elimination
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3", "H4"})
        assert core.entropy == pytest.approx(2.0)

        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})

        assert core.entropy == pytest.approx(math.log2(3))

    def test_inv5a_03_entropy_is_zero_with_singleton_survivor(self):
        """T-INV5A-03: Entropy is zero with singleton survivor (Positive)

        Setup: Core with hypothesis set {H1, H2}
        Action: Submit probe eliminating {H1}
        Assert: Entropy equals log2(1) = 0
        Protects: INV-5a — entropy reaches zero at singleton
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2"})

        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})

        assert core.entropy == pytest.approx(0.0)

    def test_inv5a_04_entropy_unchanged_when_no_elimination_occurs(self):
        """T-INV5A-04: Entropy unchanged when no elimination occurs (Positive)

        Setup: Core with hypothesis set {H1, H2, H3}
        Action: Submit probe with empty elimination set {}
        Assert: Entropy remains log2(3)
        Protects: INV-5a — entropy reflects actual eliminations only
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3"})
        initial_entropy = core.entropy

        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated=set())

        assert core.entropy == pytest.approx(initial_entropy)
        assert core.entropy == pytest.approx(math.log2(3))

    def test_inv5a_05_entropy_is_monotonically_non_increasing(self):
        """T-INV5A-05: Entropy is monotonically non-increasing (Positive)

        Setup: Core with hypothesis set {H1, H2, H3, H4, H5}
        Action: Submit sequence of probes, each eliminating one hypothesis
        Assert: Entropy after each step is <= entropy before
        Protects: INV-5a + hard-elimination constraint — entropy cannot increase
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3", "H4", "H5"})

        entropy_trace = [core.entropy]

        for i, h in enumerate(["H1", "H2", "H3", "H4"]):
            core.submit_probe_result(probe_id=f"P{i+1}", observable_id=f"O{i+1}", eliminated={h})
            entropy_trace.append(core.entropy)

        for j in range(len(entropy_trace) - 1):
            assert entropy_trace[j + 1] <= entropy_trace[j]


# -----------------------------------------------------------------------------
# 1.3 INV-6: Non-Trivial Exit
# -----------------------------------------------------------------------------


class TestINV6NonTrivialExit:
    """INV-6: An epistemic obligation may only be exited if belief has measurably changed."""

    def test_inv6_01_obligation_exit_permitted_after_elimination(self):
        """T-INV6-01: Obligation exit permitted after elimination (Positive)

        Setup: Core with active obligation O1 (min_eliminations=1)
        Action:
            1. Submit probe eliminating {H1}
            2. Request exit from O1
        Assert: Exit is permitted
        Protects: INV-6 — elimination satisfies obligation
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3"})
        core.enter_obligation(obligation_id="O1", min_eliminations=1)

        core.submit_probe_result(probe_id="P1", observable_id="O_obs", eliminated={"H1"})
        result = core.request_obligation_exit(obligation_id="O1")

        assert result.permitted is True

    def test_inv6_02_obligation_exit_rejected_with_zero_eliminations(self):
        """T-INV6-02: Obligation exit rejected with zero eliminations (Negative)

        Setup: Core with active obligation O1 (min_eliminations=1)
        Action: Request exit from O1 (no probes submitted during obligation)
        Assert: Exit is rejected
        Protects: INV-6 — obligations require substantive change
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3"})
        core.enter_obligation(obligation_id="O1", min_eliminations=1)

        result = core.request_obligation_exit(obligation_id="O1")

        assert result.permitted is False

    def test_inv6_03_obligation_exit_respects_threshold(self):
        """T-INV6-03: Obligation exit respects threshold (Negative)

        Setup: Core with active obligation O1 (min_eliminations=3)
        Action:
            1. Submit probe eliminating {H1}
            2. Submit probe eliminating {H2}
            3. Request exit from O1
        Assert: Exit is rejected (only 2 eliminations, threshold is 3)
        Protects: INV-6 — threshold enforcement is exact
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3", "H4", "H5"})
        core.enter_obligation(obligation_id="O1", min_eliminations=3)

        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        core.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={"H2"})
        result = core.request_obligation_exit(obligation_id="O1")

        assert result.permitted is False

    def test_inv6_04_obligation_exit_permitted_at_threshold(self):
        """T-INV6-04: Obligation exit permitted at threshold (Positive)

        Setup: Core with active obligation O1 (min_eliminations=2)
        Action:
            1. Submit probe eliminating {H1}
            2. Submit probe eliminating {H2}
            3. Request exit from O1
        Assert: Exit is permitted
        Protects: INV-6 — threshold is >=, not >
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3", "H4"})
        core.enter_obligation(obligation_id="O1", min_eliminations=2)

        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        core.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={"H2"})
        result = core.request_obligation_exit(obligation_id="O1")

        assert result.permitted is True

    def test_inv6_05_eliminations_outside_obligation_dont_count(self):
        """T-INV6-05: Eliminations outside obligation don't count (Negative)

        Setup: Core with hypothesis set {H1, H2, H3, H4}
        Action:
            1. Submit probe eliminating {H1} (no obligation active)
            2. Enter obligation O1 (min_eliminations=1)
            3. Request exit from O1
        Assert: Exit is rejected (elimination occurred before obligation)
        Protects: INV-6 — elimination counting is scoped to obligation
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3", "H4"})

        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        core.enter_obligation(obligation_id="O1", min_eliminations=1)
        result = core.request_obligation_exit(obligation_id="O1")

        assert result.permitted is False

    def test_inv6_06_multiple_obligations_track_independently(self):
        """T-INV6-06: Multiple obligations track independently (Positive)

        Setup: Core with hypothesis set {H1, H2, H3, H4, H5}
        Action:
            1. Enter obligation O1 (min_elim=2)
            2. Eliminate H1
            3. Enter obligation O2 (min_elim=1)
            4. Eliminate H2
            5. Request exit O2 -> permitted (1 elim during O2)
            6. Request exit O1 -> permitted (2 elim during O1)
        Assert: Both exits behave correctly based on their own scope
        Protects: INV-6 — obligations are independent scopes
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3", "H4", "H5"})

        core.enter_obligation(obligation_id="O1", min_eliminations=2)
        core.submit_probe_result(probe_id="P1", observable_id="obs1", eliminated={"H1"})
        core.enter_obligation(obligation_id="O2", min_eliminations=1)
        core.submit_probe_result(probe_id="P2", observable_id="obs2", eliminated={"H2"})

        result_o2 = core.request_obligation_exit(obligation_id="O2")
        result_o1 = core.request_obligation_exit(obligation_id="O1")

        assert result_o2.permitted is True
        assert result_o1.permitted is True


# =============================================================================
# 2. BOUNDARY / NON-LEAKAGE TESTS
# =============================================================================


# -----------------------------------------------------------------------------
# 2.1 Opaque Identifier Tests
# -----------------------------------------------------------------------------


class TestBoundaryOpaqueIdentifiers:
    """Boundary tests: core must not interpret identifier content."""

    def test_bnd_01_hypothesis_ids_are_opaque(self):
        """T-BND-01: Hypothesis IDs are opaque (arbitrary strings accepted)

        Setup: Initialize core with hypothesis set using arbitrary ID formats:
            {"uuid-1234-5678", "numeric_99", "🔬", "", "with spaces", "UPPERCASE"}
        Action: Submit probes eliminating various hypotheses
        Assert: Core operates correctly regardless of ID format
        Protects: Boundary — no hypothesis ID interpretation
        """
        hypothesis_ids = {"uuid-1234-5678", "numeric_99", "🔬", "", "with spaces", "UPPERCASE"}
        core = CMBSCore(hypothesis_ids=hypothesis_ids)

        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"🔬"})
        core.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={""})

        assert core.survivors == {"uuid-1234-5678", "numeric_99", "with spaces", "UPPERCASE"}

    def test_bnd_02_probe_ids_are_opaque(self):
        """T-BND-02: Probe IDs are opaque (arbitrary strings accepted)

        Setup: Core with hypothesis set {H1, H2}
        Action: Submit probes with arbitrary ID formats:
            "probe-alpha", "12345", "émoji🎯", ""
        Assert: All unique probe IDs are accepted
        Protects: Boundary — no probe ID interpretation
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2"})

        r1 = core.submit_probe_result(probe_id="probe-alpha", observable_id="O1", eliminated=set())
        r2 = core.submit_probe_result(probe_id="12345", observable_id="O2", eliminated=set())
        r3 = core.submit_probe_result(probe_id="émoji🎯", observable_id="O3", eliminated=set())
        r4 = core.submit_probe_result(probe_id="", observable_id="O4", eliminated=set())

        assert r1.accepted is True
        assert r2.accepted is True
        assert r3.accepted is True
        assert r4.accepted is True

    def test_bnd_03_observable_ids_are_opaque(self):
        """T-BND-03: Observable IDs are opaque (arbitrary strings accepted)

        Setup: Core with hypothesis set {H1, H2, H3}
        Action: Submit probe with observable ID "anything_at_all_here"
        Assert: Core accepts and processes normally
        Protects: Boundary — no observable ID interpretation
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3"})

        result = core.submit_probe_result(
            probe_id="P1", observable_id="anything_at_all_here", eliminated={"H1"}
        )

        assert result.accepted is True
        assert core.survivors == {"H2", "H3"}

    def test_bnd_04_conclusion_ids_are_opaque(self):
        """T-BND-04: Conclusion IDs are opaque (arbitrary strings accepted)

        Setup: Core with stability tracking enabled
        Action: Declare conclusions with arbitrary IDs:
            "conclusion_X", "42", "true", "compliant", "unknown"
        Assert: Core tracks stability regardless of ID content
        Protects: Boundary — no conclusion ID interpretation
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2"}, stability_window=3)

        core.declare_conclusion(conclusion_id="conclusion_X")
        core.declare_conclusion(conclusion_id="42")
        core.declare_conclusion(conclusion_id="true")
        core.declare_conclusion(conclusion_id="compliant")
        core.declare_conclusion(conclusion_id="unknown")

        # No assertion on specific behavior, just that no error occurs
        # Core should track these without interpreting their meaning

    def test_bnd_05_ids_that_look_like_domain_concepts_are_not_special_cased(self):
        """T-BND-05: IDs that "look like" domain concepts are not special-cased

        Setup: Core with hypothesis set {"compliant", "non_compliant", "error"}
        Action: Eliminate hypothesis "compliant"
        Assert: Core treats this as ordinary elimination, no special behavior
        Protects: Boundary — no domain concept recognition
        """
        core = CMBSCore(hypothesis_ids={"compliant", "non_compliant", "error"})

        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"compliant"})

        assert core.survivors == {"non_compliant", "error"}
        assert core.entropy == pytest.approx(math.log2(2))


# -----------------------------------------------------------------------------
# 2.2 Non-Singleton Termination Tests
# -----------------------------------------------------------------------------


class TestBoundaryNonSingletonTermination:
    """Boundary tests: termination must not assume singleton survivor."""

    def test_bnd_06_termination_permitted_with_multiple_survivors(self):
        """T-BND-06: Termination permitted with multiple survivors

        Setup: Core with hypothesis set {H1, H2, H3}, stability window = 2
        Action:
            1. Declare conclusion C1
            2. Declare conclusion C1 (stable for 2 steps)
            3. Request termination
        Assert: Termination permitted (stability satisfied, survivor count irrelevant)
        Protects: Boundary — no singleton assumption (Risk L6)
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3"}, stability_window=2)

        core.declare_conclusion(conclusion_id="C1")
        core.declare_conclusion(conclusion_id="C1")
        result = core.request_termination()

        assert result.permitted is True

    def test_bnd_07_termination_permitted_with_zero_survivors(self):
        """T-BND-07: Termination permitted with zero survivors

        Setup: Core with hypothesis set {H1}, stability window = 2
        Action:
            1. Eliminate H1 (zero survivors)
            2. Declare conclusion C1
            3. Declare conclusion C1
            4. Request termination
        Assert: Termination permitted (stability satisfied)
        Protects: Boundary — zero-survivor termination is valid
        """
        core = CMBSCore(hypothesis_ids={"H1"}, stability_window=2)

        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        core.declare_conclusion(conclusion_id="C1")
        core.declare_conclusion(conclusion_id="C1")
        result = core.request_termination()

        assert result.permitted is True


# -----------------------------------------------------------------------------
# 2.3 Non-Binary Conclusion Tests
# -----------------------------------------------------------------------------


class TestBoundaryNonBinaryConclusion:
    """Boundary tests: conclusions must not be assumed binary."""

    def test_bnd_08_more_than_two_distinct_conclusions_supported(self):
        """T-BND-08: More than two distinct conclusions supported

        Setup: Core with stability tracking, window = 3
        Action: Declare conclusions in sequence: C1, C2, C3, C4, C5
        Assert: Core tracks all five without error
        Protects: Boundary — no binary conclusion assumption (Risk L2)
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2"}, stability_window=3)

        core.declare_conclusion(conclusion_id="C1")
        core.declare_conclusion(conclusion_id="C2")
        core.declare_conclusion(conclusion_id="C3")
        core.declare_conclusion(conclusion_id="C4")
        core.declare_conclusion(conclusion_id="C5")

        # No error should occur

    def test_bnd_09_conclusion_stability_works_for_any_conclusion_value(self):
        """T-BND-09: Conclusion stability works for any conclusion value

        Setup: Core with stability window = 3
        Action:
            1. Declare C1, C1, C1 (stable)
            2. Request termination
        Assert: Termination permitted
        Action (continued):
            3. New session: Declare C99, C99, C99 (stable)
            4. Request termination
        Assert: Termination permitted (C99 is treated same as C1)
        Protects: Boundary — all conclusions are equal to core
        """
        # First session with C1
        core1 = CMBSCore(hypothesis_ids={"H1", "H2"}, stability_window=3)
        core1.declare_conclusion(conclusion_id="C1")
        core1.declare_conclusion(conclusion_id="C1")
        core1.declare_conclusion(conclusion_id="C1")
        result1 = core1.request_termination()
        assert result1.permitted is True

        # Second session with C99
        core2 = CMBSCore(hypothesis_ids={"H1", "H2"}, stability_window=3)
        core2.declare_conclusion(conclusion_id="C99")
        core2.declare_conclusion(conclusion_id="C99")
        core2.declare_conclusion(conclusion_id="C99")
        result2 = core2.request_termination()
        assert result2.permitted is True


# -----------------------------------------------------------------------------
# 2.4 Non-Execution Semantics Tests
# -----------------------------------------------------------------------------


class TestBoundaryNonExecutionSemantics:
    """Boundary tests: core must not assume execution model."""

    def test_bnd_10_no_attempt_or_success_states_exist(self):
        """T-BND-10: No "attempt" or "success" states exist

        Setup: Query core for available states/enums
        Assert: No state named "attempted," "successful," "failed," "pending," or similar
        Protects: Boundary — no execution model assumption (Risk L1)
        """
        # Inspect core API for execution-model terms
        forbidden_terms = {"attempted", "successful", "failed", "pending", "executing", "running"}

        # Check class attributes and methods
        core_members = dir(CMBSCore)
        for member in core_members:
            member_lower = member.lower()
            for term in forbidden_terms:
                assert term not in member_lower, f"Core contains execution-model term: {member}"

    def test_bnd_11_probe_results_are_observations_not_executions(self):
        """T-BND-11: Probe results are observations, not executions

        Setup: Core with hypothesis set {H1, H2, H3}
        Action: Submit probe result (no "execute" API exists)
        Assert: Core accepts via submit_probe_result or equivalent observation-framed API
        Protects: Boundary — vocabulary is observational, not agentic
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3"})

        # Verify observation-framed API exists
        assert hasattr(core, "submit_probe_result")

        # Verify execution-framed API does not exist
        assert not hasattr(core, "execute_probe")
        assert not hasattr(core, "run_probe")

        result = core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        assert result.accepted is True

    def test_bnd_12_core_has_no_probe_scheduling_capability(self):
        """T-BND-12: Core has no probe scheduling capability

        Setup: Inspect core API
        Assert: No method exists to "execute probe," "run probe," "schedule probe," or "select next probe"
        Protects: Boundary — probe execution is outside core
        """
        scheduling_methods = [
            "execute_probe",
            "run_probe",
            "schedule_probe",
            "select_next_probe",
            "get_next_probe",
            "recommend_probe",
        ]

        for method in scheduling_methods:
            assert not hasattr(CMBSCore, method), f"Core should not have method: {method}"


# =============================================================================
# 3. OBLIGATION & TERMINATION TESTS
# =============================================================================


# -----------------------------------------------------------------------------
# 3.1 Obligation Discipline
# -----------------------------------------------------------------------------


class TestObligationDiscipline:
    """Obligation lifecycle and scoping tests."""

    def test_obl_01_obligation_entry_is_adapter_initiated(self):
        """T-OBL-01: Obligation entry is adapter-initiated

        Setup: Core with no active obligations
        Action: Adapter calls enter_obligation(O1, params)
        Assert: Obligation O1 is now active
        Protects: Boundary — adapter controls obligation lifecycle
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3"})

        core.enter_obligation(obligation_id="O1", min_eliminations=1)

        assert core.is_obligation_active(obligation_id="O1") is True

    def test_obl_02_obligation_cannot_self_trigger(self):
        """T-OBL-02: Obligation cannot self-trigger

        Setup: Core with hypothesis set, no obligations
        Action: Submit probes causing eliminations
        Assert: No obligation becomes active without adapter explicitly entering it
        Protects: Boundary — core doesn't decide when obligations trigger
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3"})

        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        core.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={"H2"})

        assert core.active_obligations == set()

    def test_obl_03_obligation_parameters_are_adapter_provided(self):
        """T-OBL-03: Obligation parameters are adapter-provided

        Setup: Core ready for obligation
        Action: Enter obligation with adapter-specified parameters:
            enter_obligation("O1", min_eliminations=5, entropy_threshold=0.5)
        Assert: Core uses exactly these parameters, not defaults
        Protects: Boundary — no hardcoded thresholds (Risk L4)
        """
        core = CMBSCore(hypothesis_ids={f"H{i}" for i in range(1, 11)})

        core.enter_obligation(obligation_id="O1", min_eliminations=5)

        # Eliminate 4 hypotheses (below threshold)
        for i in range(1, 5):
            core.submit_probe_result(probe_id=f"P{i}", observable_id=f"O{i}", eliminated={f"H{i}"})

        result = core.request_obligation_exit(obligation_id="O1")
        assert result.permitted is False  # Need 5, only have 4

        # Eliminate 5th hypothesis
        core.submit_probe_result(probe_id="P5", observable_id="O5", eliminated={"H5"})
        result = core.request_obligation_exit(obligation_id="O1")
        assert result.permitted is True

    def test_obl_04_nested_obligations_are_independent(self):
        """T-OBL-04: Nested obligations are independent

        Setup: Core with hypothesis set {H1, H2, H3, H4, H5}
        Action:
            1. Enter O1 (min_elim=2)
            2. Eliminate H1
            3. Enter O2 (min_elim=1)
            4. Eliminate H2
            5. Request exit O2 -> permitted (1 elim during O2)
            6. Request exit O1 -> permitted (2 elim during O1)
        Assert: Both exits behave correctly based on their own scope
        Protects: INV-6 — obligation scopes are independent
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3", "H4", "H5"})

        core.enter_obligation(obligation_id="O1", min_eliminations=2)
        core.submit_probe_result(probe_id="P1", observable_id="obs1", eliminated={"H1"})
        core.enter_obligation(obligation_id="O2", min_eliminations=1)
        core.submit_probe_result(probe_id="P2", observable_id="obs2", eliminated={"H2"})

        result_o2 = core.request_obligation_exit(obligation_id="O2")
        result_o1 = core.request_obligation_exit(obligation_id="O1")

        assert result_o2.permitted is True
        assert result_o1.permitted is True

    def test_obl_05_exiting_non_existent_obligation_fails_gracefully(self):
        """T-OBL-05: Exiting non-existent obligation fails gracefully

        Setup: Core with no active obligations
        Action: Request exit from "O_nonexistent"
        Assert: Request fails or returns "not active" (no crash, no side effects)
        Protects: Robustness — invalid requests handled cleanly
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2"})

        result = core.request_obligation_exit(obligation_id="O_nonexistent")

        assert result.permitted is False or result.error is not None


# -----------------------------------------------------------------------------
# 3.2 Entropy Observation (Not Gating)
# -----------------------------------------------------------------------------


class TestEntropyObservation:
    """Entropy is observable but does not gate operations."""

    def test_ent_01_entropy_is_queryable_at_any_time(self):
        """T-ENT-01: Entropy is queryable at any time

        Setup: Core with hypothesis set
        Action: Query entropy before, during, and after eliminations
        Assert: Entropy value returned at each query
        Protects: INV-5a — entropy is observable
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3", "H4"})

        # Before eliminations
        e1 = core.entropy
        assert e1 is not None
        assert e1 == pytest.approx(2.0)

        # During eliminations
        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        e2 = core.entropy
        assert e2 is not None
        assert e2 == pytest.approx(math.log2(3))

        # After more eliminations
        core.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={"H2"})
        e3 = core.entropy
        assert e3 is not None
        assert e3 == pytest.approx(1.0)

    def test_ent_02_entropy_does_not_gate_termination(self):
        """T-ENT-02: Entropy does not gate termination

        Setup: Core with hypothesis set {H1, H2, H3, H4}, stability window = 2
        Action:
            1. Declare C1, C1 (stable)
            2. Request termination (entropy = log2(4) = 2.0, high uncertainty)
        Assert: Termination permitted (entropy is high but irrelevant)
        Protects: Boundary — entropy is diagnostic, not a gate (Ambiguity A resolution)
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3", "H4"}, stability_window=2)

        core.declare_conclusion(conclusion_id="C1")
        core.declare_conclusion(conclusion_id="C1")

        # Entropy is still high (no eliminations)
        assert core.entropy == pytest.approx(2.0)

        result = core.request_termination()
        assert result.permitted is True

    def test_ent_03_entropy_does_not_gate_obligation_exit(self):
        """T-ENT-03: Entropy does not gate obligation exit

        Setup: Core with active obligation (min_eliminations=1)
        Action:
            1. Eliminate one hypothesis
            2. Request obligation exit (entropy still high)
        Assert: Exit permitted (elimination threshold met, entropy irrelevant)
        Protects: INV-6 — obligation exit is elimination-gated, not entropy-gated
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3", "H4", "H5"})
        core.enter_obligation(obligation_id="O1", min_eliminations=1)

        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})

        # Entropy is still high
        assert core.entropy == pytest.approx(2.0)

        result = core.request_obligation_exit(obligation_id="O1")
        assert result.permitted is True

    def test_ent_04_zero_entropy_does_not_auto_terminate(self):
        """T-ENT-04: Zero entropy does not auto-terminate

        Setup: Core with hypothesis set {H1, H2}, stability window = 2
        Action:
            1. Eliminate H1 (entropy = 0, singleton survivor)
            2. Do NOT request termination
        Assert: Core remains active, no auto-termination
        Protects: Boundary — termination requires explicit adapter request
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2"}, stability_window=2)

        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})

        assert core.entropy == pytest.approx(0.0)
        assert core.is_terminated is False


# -----------------------------------------------------------------------------
# 3.3 Termination Discipline
# -----------------------------------------------------------------------------


class TestTerminationDiscipline:
    """Termination lifecycle and stability tests."""

    def test_term_01_termination_requires_explicit_adapter_request(self):
        """T-TERM-01: Termination requires explicit adapter request

        Setup: Core with hypothesis set, stability window = 2, conclusion stable
        Action: Do not call request_termination
        Assert: Core remains active indefinitely
        Protects: Boundary — adapter controls termination
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2"}, stability_window=2)

        core.declare_conclusion(conclusion_id="C1")
        core.declare_conclusion(conclusion_id="C1")
        # Stability achieved but no termination request

        assert core.is_terminated is False

    def test_term_02_termination_rejected_if_conclusion_unstable(self):
        """T-TERM-02: Termination rejected if conclusion unstable

        Setup: Core with stability window = 3
        Action:
            1. Declare C1
            2. Declare C2 (changed)
            3. Request termination
        Assert: Termination rejected (conclusion not stable)
        Protects: INV-2 — stability is enforced
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2"}, stability_window=3)

        core.declare_conclusion(conclusion_id="C1")
        core.declare_conclusion(conclusion_id="C2")
        result = core.request_termination()

        assert result.permitted is False

    def test_term_03_termination_permitted_after_stability_achieved(self):
        """T-TERM-03: Termination permitted after stability achieved

        Setup: Core with stability window = 3
        Action:
            1. Declare C1, C1, C1
            2. Request termination
        Assert: Termination permitted
        Protects: INV-2 — stability gating works correctly
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2"}, stability_window=3)

        core.declare_conclusion(conclusion_id="C1")
        core.declare_conclusion(conclusion_id="C1")
        core.declare_conclusion(conclusion_id="C1")
        result = core.request_termination()

        assert result.permitted is True

    def test_term_04_stability_resets_on_conclusion_change(self):
        """T-TERM-04: Stability resets on conclusion change

        Setup: Core with stability window = 3
        Action:
            1. Declare C1, C1 (2 stable steps)
            2. Declare C2 (change)
            3. Request termination
        Assert: Termination rejected (stability reset by C2)
        Protects: INV-2 — stability window is rolling, not cumulative
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2"}, stability_window=3)

        core.declare_conclusion(conclusion_id="C1")
        core.declare_conclusion(conclusion_id="C1")
        core.declare_conclusion(conclusion_id="C2")
        result = core.request_termination()

        assert result.permitted is False

    def test_term_05_termination_with_stability_disabled(self):
        """T-TERM-05: Termination with stability disabled

        Setup: Core initialized with stability_window = 0 (disabled)
        Action:
            1. Declare C1
            2. Request termination immediately
        Assert: Termination permitted (no stability requirement)
        Protects: Configuration — stability is optional (INV-2 is optional)
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2"}, stability_window=0)

        core.declare_conclusion(conclusion_id="C1")
        result = core.request_termination()

        assert result.permitted is True

    def test_term_06_termination_independent_of_obligation_state(self):
        """T-TERM-06: Termination independent of obligation state

        Setup: Core with active obligation O1
        Action:
            1. Declare C1, C1, C1 (stable)
            2. Request termination (obligation still active)
        Assert: Termination permitted (obligation is separate from termination)
        Protects: Boundary — termination and obligations are orthogonal
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3"}, stability_window=3)

        core.enter_obligation(obligation_id="O1", min_eliminations=1)
        core.declare_conclusion(conclusion_id="C1")
        core.declare_conclusion(conclusion_id="C1")
        core.declare_conclusion(conclusion_id="C1")

        assert core.is_obligation_active(obligation_id="O1") is True
        result = core.request_termination()
        assert result.permitted is True


# =============================================================================
# 4. STRANGLER FIG MIGRATION SUPPORT TESTS
# =============================================================================


# -----------------------------------------------------------------------------
# 4.1 Legacy Compatibility
# -----------------------------------------------------------------------------


class TestMigrationLegacyCompatibility:
    """Tests for strangler fig migration support."""

    def test_mig_01_core_accepts_legacy_format_ids(self):
        """T-MIG-01: Core accepts legacy-format IDs

        Setup: Initialize core with IDs matching legacy system format
        Action: Perform standard operations
        Assert: Core functions correctly
        Protects: Migration — legacy ID formats are valid opaque IDs
        """
        # Legacy format example: prefixed identifiers
        legacy_hypothesis_ids = {
            "LEGACY_HYP_001",
            "LEGACY_HYP_002",
            "LEGACY_HYP_003",
        }
        core = CMBSCore(hypothesis_ids=legacy_hypothesis_ids)

        result = core.submit_probe_result(
            probe_id="LEGACY_PROBE_001",
            observable_id="LEGACY_OBS_001",
            eliminated={"LEGACY_HYP_001"},
        )

        assert result.accepted is True
        assert core.survivors == {"LEGACY_HYP_002", "LEGACY_HYP_003"}

    def test_mig_02_core_operates_with_partial_hypothesis_elimination(self):
        """T-MIG-02: Core operates with partial hypothesis elimination

        Setup: Core with large hypothesis set (100 hypotheses)
        Action: Eliminate only 5 hypotheses, then query state
        Assert: Core correctly reports 95 survivors, correct entropy
        Protects: Migration — incremental elimination is valid
        """
        hypothesis_ids = {f"H{i}" for i in range(1, 101)}
        core = CMBSCore(hypothesis_ids=hypothesis_ids)

        for i in range(1, 6):
            core.submit_probe_result(
                probe_id=f"P{i}", observable_id=f"O{i}", eliminated={f"H{i}"}
            )

        assert len(core.survivors) == 95
        assert core.entropy == pytest.approx(math.log2(95))

    def test_mig_03_core_state_is_serializable(self):
        """T-MIG-03: Core state is serializable

        Setup: Core with hypothesis set, some eliminations, active obligation
        Action: Serialize core state, deserialize into new instance
        Assert: New instance has identical state
        Protects: Migration — state can be checkpointed and transferred
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3", "H4"}, stability_window=2)
        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        core.enter_obligation(obligation_id="O1", min_eliminations=1)

        # Serialize
        state = core.serialize()

        # Deserialize into new instance
        core2 = CMBSCore.deserialize(state)

        assert core2.survivors == core.survivors
        assert core2.entropy == pytest.approx(core.entropy)
        assert core2.consumed_probes == core.consumed_probes
        assert core2.active_obligations == core.active_obligations

    def test_mig_04_adapter_can_replay_historical_eliminations(self):
        """T-MIG-04: Adapter can replay historical eliminations

        Setup: Empty core
        Action: Submit batch of historical elimination events in order
        Assert: Core reaches expected state (correct survivors, correct entropy)
        Protects: Migration — historical events can bootstrap core state
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3", "H4", "H5"})

        # Historical events in order
        historical_events = [
            ("P1", "O1", {"H1"}),
            ("P2", "O2", {"H3"}),
            ("P3", "O3", {"H5"}),
        ]

        for probe_id, observable_id, eliminated in historical_events:
            core.submit_probe_result(
                probe_id=probe_id, observable_id=observable_id, eliminated=eliminated
            )

        assert core.survivors == {"H2", "H4"}
        assert core.entropy == pytest.approx(math.log2(2))


# -----------------------------------------------------------------------------
# 4.2 Incremental Adoption
# -----------------------------------------------------------------------------


class TestMigrationIncrementalAdoption:
    """Tests for running core alongside legacy systems."""

    def test_mig_05_core_can_run_alongside_legacy_system(self):
        """T-MIG-05: Core can run alongside legacy system

        Setup: Core receives same elimination events as legacy system (shadow mode)
        Action: Compare core entropy with legacy entropy calculation
        Assert: Values match (within floating-point tolerance)
        Protects: Migration — core can validate against legacy before cutover
        """
        hypothesis_ids = {"H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8"}
        core = CMBSCore(hypothesis_ids=hypothesis_ids)

        # Simulate shadow mode: feed same events to both systems
        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1", "H2"})
        core.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={"H5"})

        # Legacy calculation (inline, not using helper)
        legacy_survivor_count = 5  # 8 - 3 eliminated
        legacy_entropy = math.log2(legacy_survivor_count)

        assert core.entropy == pytest.approx(legacy_entropy)

    def test_mig_06_core_provides_audit_trail_for_comparison(self):
        """T-MIG-06: Core provides audit trail for comparison

        Setup: Core with elimination history
        Action: Query full elimination history
        Assert: Core returns ordered list of (probe_id, observable_id, eliminated_hypotheses) events
        Protects: Migration — audit trail enables legacy comparison
        """
        core = CMBSCore(hypothesis_ids={"H1", "H2", "H3", "H4"})

        core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
        core.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={"H3"})

        history = core.get_elimination_history()

        assert len(history) == 2
        assert history[0].probe_id == "P1"
        assert history[0].observable_id == "O1"
        assert history[0].eliminated == {"H1"}
        assert history[1].probe_id == "P2"
        assert history[1].observable_id == "O2"
        assert history[1].eliminated == {"H3"}
