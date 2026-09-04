"""
Snapshot, OntologyBundle, and result types for the unified Session kernel.

The kernel stores no mutable state — every read is a ``Snapshot`` derived
from reducing the op log. ``Snapshot`` is therefore a frozen, copyable,
serializable record of what the session believed at a particular sequence
point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OntologyBundle:
    """Versioned reference to the hypothesis space and causal graph.

    Kernel does not interpret these strings; they are stored on the session
    so callers and auditors can verify they're operating against the
    intended ontology.
    """

    hypothesis_space_id: str
    hypothesis_version: str
    causal_graph_ref: str = "none"
    causal_graph_version: str = "v0"


@dataclass(frozen=True)
class ObligationEntry:
    """Internal snapshot record of one active obligation."""

    obligation_id: str
    min_eliminations: int
    eliminations_in_scope: int


@dataclass(frozen=True)
class Snapshot:
    """Immutable read view of a session at a given sequence point.

    Produced by ``Reducer.reduce``; returned by ``Session.snapshot()`` and
    embedded in ``AppendResult.state_hash_after`` indirectly via hashing.

    ``seq`` is the log position the snapshot reflects — the ``seq`` of the
    last envelope folded in, accepted or not (0 for a fresh session).
    ``stability_window`` is session configuration carried on the snapshot
    so that a reducer can gate ``request_termination`` (INV-2) from the
    snapshot alone.
    """

    session_id: str
    seq: int
    state_hash: str
    survivors: frozenset[str]
    eliminated: frozenset[str]
    consumed_op_ids: frozenset[str]
    obligations: tuple[ObligationEntry, ...]
    conclusion_history: tuple[str, ...]
    terminated: bool
    attrs: dict[str, Any] = field(default_factory=dict)
    stability_window: int = 0

    @property
    def n_survivors(self) -> int:
        return len(self.survivors)

    @property
    def entropy(self) -> float:
        """``log₂(|survivors|)``; 0.0 when ``|survivors| <= 1`` (INV-5a).

        Diagnostic only — the kernel never uses entropy as a gate.
        """
        n = self.n_survivors
        return 0.0 if n <= 1 else math.log2(n)

    @property
    def active_obligations(self) -> frozenset[str]:
        return frozenset(o.obligation_id for o in self.obligations)

    def obligation(self, obligation_id: str) -> ObligationEntry | None:
        """Return the active obligation with this ID, or ``None``."""
        for entry in self.obligations:
            if entry.obligation_id == obligation_id:
                return entry
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "seq": self.seq,
            "state_hash": self.state_hash,
            "survivors": sorted(self.survivors),
            "n_survivors": self.n_survivors,
            "entropy": self.entropy,
            "eliminated": sorted(self.eliminated),
            "consumed_op_ids": sorted(self.consumed_op_ids),
            "obligations": [
                {
                    "obligation_id": o.obligation_id,
                    "min_eliminations": o.min_eliminations,
                    "eliminations_in_scope": o.eliminations_in_scope,
                }
                for o in self.obligations
            ],
            "active_obligations": sorted(self.active_obligations),
            "conclusion_history": list(self.conclusion_history),
            "terminated": self.terminated,
            "attrs": dict(self.attrs),
            "stability_window": self.stability_window,
        }


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of ``Session.submit_probe_result``.

    ``eliminated`` is the set of hypotheses this probe newly removed;
    ``already_eliminated`` is the requested subset that had been removed
    by an earlier op. IDs outside the session's universe are ignored and
    appear in neither.
    """

    accepted: bool
    error: str | None = None
    eliminated: frozenset[str] = frozenset()
    already_eliminated: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ObligationExitResult:
    """Outcome of ``Session.request_obligation_exit``."""

    permitted: bool
    error: str | None = None


@dataclass(frozen=True)
class TerminationResult:
    """Outcome of ``Session.request_termination``."""

    permitted: bool
    error: str | None = None
