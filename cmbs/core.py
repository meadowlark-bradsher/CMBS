"""
CMBS v0 Core.

Core belief-state accounting API and implementation.
Opaque identifiers only, no domain semantics, adapter-provided thresholds.
"""

import math
from dataclasses import dataclass
from typing import Any


@dataclass
class ProbeResult:
    """Result of submitting a probe observation."""
    accepted: bool
    error: str | None = None


@dataclass
class ObligationExitResult:
    """Result of requesting obligation exit."""
    permitted: bool
    error: str | None = None


@dataclass
class TerminationResult:
    """Result of requesting termination."""
    permitted: bool
    error: str | None = None


@dataclass
class EliminationEvent:
    """Record of a single elimination event."""
    probe_id: str
    observable_id: str
    eliminated: set[str]


class CMBSCore:
    """
    CMBS v0 Core - Belief-state accounting system.

    Tracks hypotheses, counts eliminations, measures entropy, and enforces non-repetition.
    Does not know what hypotheses mean, what probes do, or when to terminate.
    All semantics live in adapters. Core provides mechanism; adapters provide policy.
    """

    def __init__(
        self,
        hypothesis_ids: set[str],
        stability_window: int = 0,
    ) -> None:
        """
        Initialize the core with a hypothesis set.

        Args:
            hypothesis_ids: Initial set of opaque hypothesis identifiers
            stability_window: Number of consecutive identical conclusions required
                              for stability (0 = disabled)
        """
        self._survivors: set[str] = set(hypothesis_ids)
        self._consumed_probes: set[str] = set()
        self._stability_window: int = stability_window
        self._conclusion_history: list[str] = []
        self._terminated: bool = False
        self._obligations: dict[str, int] = {}  # obligation_id -> min_eliminations
        self._obligation_elimination_counts: dict[str, int] = {}  # obligation_id -> count
        self._elimination_history: list[EliminationEvent] = []

    @property
    def survivors(self) -> set[str]:
        """Return the current set of surviving hypothesis IDs."""
        return set(self._survivors)

    @property
    def entropy(self) -> float:
        """Return current entropy: log2(|survivors|). Returns 0 if |survivors| <= 1."""
        n = len(self._survivors)
        if n <= 1:
            return 0.0
        return math.log2(n)

    @property
    def consumed_probes(self) -> set[str]:
        """Return the set of probe IDs that have been consumed."""
        return set(self._consumed_probes)

    @property
    def active_obligations(self) -> set[str]:
        """Return the set of currently active obligation IDs."""
        return set(self._obligations.keys())

    @property
    def is_terminated(self) -> bool:
        """Return True if termination has been granted."""
        return self._terminated

    def submit_probe_result(
        self,
        probe_id: str,
        observable_id: str,
        eliminated: set[str],
    ) -> ProbeResult:
        """
        Submit an observation from a probe.

        This is the observation-framed API. Core does not execute probes;
        it receives observations about what probes found.

        Args:
            probe_id: Opaque identifier for this probe (must be unique)
            observable_id: Opaque identifier for the observable
            eliminated: Set of hypothesis IDs eliminated by this observation

        Returns:
            ProbeResult with accepted=True if probe was accepted,
            accepted=False if probe was duplicate
        """
        # INV-3: Reject duplicate probes
        if probe_id in self._consumed_probes:
            return ProbeResult(accepted=False, error="duplicate probe")

        # Record probe consumption
        self._consumed_probes.add(probe_id)

        # Apply eliminations (core trusts adapter)
        actual_eliminated = eliminated & self._survivors
        self._survivors -= actual_eliminated

        # Record elimination event for audit trail
        if actual_eliminated:
            self._elimination_history.append(
                EliminationEvent(
                    probe_id=probe_id,
                    observable_id=observable_id,
                    eliminated=actual_eliminated,
                )
            )
            # Update elimination counts for active obligations
            for obl_id in self._obligations:
                self._obligation_elimination_counts[obl_id] += len(actual_eliminated)

        return ProbeResult(accepted=True)

    def enter_obligation(
        self,
        obligation_id: str,
        min_eliminations: int = 1,
    ) -> None:
        """
        Enter an epistemic obligation.

        Adapter initiates obligations; core does not self-trigger.

        Args:
            obligation_id: Opaque identifier for this obligation
            min_eliminations: Minimum eliminations required to exit (adapter-provided)
        """
        self._obligations[obligation_id] = min_eliminations
        self._obligation_elimination_counts[obligation_id] = 0

    def request_obligation_exit(
        self,
        obligation_id: str,
    ) -> ObligationExitResult:
        """
        Request to exit an obligation.

        Exit is permitted only if enough eliminations have occurred within
        the obligation's scope (INV-6).

        Args:
            obligation_id: Opaque identifier of obligation to exit

        Returns:
            ObligationExitResult with permitted=True if exit allowed
        """
        if obligation_id not in self._obligations:
            return ObligationExitResult(permitted=False, error="obligation not active")

        min_elim = self._obligations[obligation_id]
        actual_elim = self._obligation_elimination_counts[obligation_id]

        if actual_elim >= min_elim:
            # Exit permitted, remove obligation
            del self._obligations[obligation_id]
            del self._obligation_elimination_counts[obligation_id]
            return ObligationExitResult(permitted=True)
        else:
            return ObligationExitResult(permitted=False)

    def is_obligation_active(self, obligation_id: str) -> bool:
        """Check if an obligation is currently active."""
        return obligation_id in self._obligations

    def declare_conclusion(self, conclusion_id: str) -> None:
        """
        Declare the current conclusion.

        Core tracks conclusion stability but does not interpret conclusion meaning.

        Args:
            conclusion_id: Opaque identifier for the conclusion
        """
        self._conclusion_history.append(conclusion_id)

    def request_termination(self) -> TerminationResult:
        """
        Request termination.

        Termination requires:
        - Explicit adapter request (this method)
        - Stability window satisfied (if enabled)

        Termination does NOT require:
        - Singleton survivor
        - Low entropy
        - All obligations closed

        Returns:
            TerminationResult with permitted=True if termination allowed
        """
        # If stability is disabled (window=0), permit immediately
        if self._stability_window == 0:
            self._terminated = True
            return TerminationResult(permitted=True)

        # Check stability: last N conclusions must be identical
        if len(self._conclusion_history) < self._stability_window:
            return TerminationResult(permitted=False)

        recent = self._conclusion_history[-self._stability_window:]
        if len(set(recent)) == 1:
            self._terminated = True
            return TerminationResult(permitted=True)
        else:
            return TerminationResult(permitted=False)

    def get_elimination_history(self) -> list[EliminationEvent]:
        """
        Return ordered list of elimination events for audit trail.

        Returns:
            List of EliminationEvent records in submission order
        """
        return list(self._elimination_history)

    def serialize(self) -> Any:
        """
        Serialize core state for checkpointing.

        Returns:
            Serializable representation of core state
        """
        return {
            "survivors": list(self._survivors),
            "consumed_probes": list(self._consumed_probes),
            "stability_window": self._stability_window,
            "conclusion_history": list(self._conclusion_history),
            "terminated": self._terminated,
            "obligations": dict(self._obligations),
            "obligation_elimination_counts": dict(self._obligation_elimination_counts),
            "elimination_history": [
                {
                    "probe_id": e.probe_id,
                    "observable_id": e.observable_id,
                    "eliminated": list(e.eliminated),
                }
                for e in self._elimination_history
            ],
        }

    @classmethod
    def deserialize(cls, state: Any) -> "CMBSCore":
        """
        Deserialize core state from checkpoint.

        Args:
            state: Previously serialized state

        Returns:
            New CMBSCore instance with restored state
        """
        # Create instance with empty hypothesis set (will be overwritten)
        instance = cls(hypothesis_ids=set(), stability_window=state["stability_window"])
        instance._survivors = set(state["survivors"])
        instance._consumed_probes = set(state["consumed_probes"])
        instance._conclusion_history = list(state["conclusion_history"])
        instance._terminated = state["terminated"]
        instance._obligations = dict(state["obligations"])
        instance._obligation_elimination_counts = dict(state["obligation_elimination_counts"])
        instance._elimination_history = [
            EliminationEvent(
                probe_id=e["probe_id"],
                observable_id=e["observable_id"],
                eliminated=set(e["eliminated"]),
            )
            for e in state["elimination_history"]
        ]
        return instance
