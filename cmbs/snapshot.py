"""
Snapshot, OntologyBundle, and result types for the unified Session kernel.

The kernel stores no mutable state — every read is a ``Snapshot`` derived
from reducing the op log. ``Snapshot`` is therefore a frozen, copyable,
serializable record of what the session believed at a particular sequence
point.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


def compute_position_digest(survivors: Iterable[str]) -> str:
    """SHA-256 over the sorted survivor set, and nothing else.

    This names a *position in the belief lattice* independently of which
    session, log, or reducer produced it. Two sessions with the same
    survivors have the same digest whatever their IDs, log lengths,
    obligations, or conclusion history. Compare it to ``state_hash``,
    which deliberately covers all of those.

    The universe is not included: the digest is the subset, and callers
    who need "this point in *this* lattice" pair it with the initial
    hypothesis set.
    """
    body = json.dumps(sorted(set(survivors)), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


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


OBLIGATION_GROSS = "gross"
OBLIGATION_NET = "net"
OBLIGATION_SEMANTICS = frozenset({OBLIGATION_GROSS, OBLIGATION_NET})


@dataclass(frozen=True)
class ObligationEntry:
    """Internal snapshot record of one active obligation.

    ``eliminations_in_scope`` is the running count of hypotheses newly
    removed since the obligation opened; it is what ``gross`` semantics
    measure. The remaining fields are populated only by reducers that
    support reinstatement: ``open_seq`` is the seq of the accepted
    ``enter_obligation``, ``semantics`` is ``"gross"`` or ``"net"``, and
    ``dead_at_open`` is the eliminated set at that moment, against which
    ``net`` progress is computed.
    """

    obligation_id: str
    min_eliminations: int
    eliminations_in_scope: int
    open_seq: int = 0
    semantics: str = OBLIGATION_GROSS
    dead_at_open: frozenset[str] = frozenset()

    def progress(self, eliminated: frozenset[str]) -> int:
        """Progress toward ``min_eliminations`` under this entry's semantics.

        ``gross``: the in-scope count. ``net``: ``|eliminated \\ dead_at_open|``,
        the hypotheses dead now that were live when the obligation opened.
        """
        if self.semantics == OBLIGATION_NET:
            return len(eliminated - self.dead_at_open)
        return self.eliminations_in_scope


@dataclass(frozen=True)
class ClosedObligation:
    """Frozen record of an obligation that exited successfully.

    Keyed by ``(obligation_id, open_seq)``: an obligation may be re-entered
    after exit, so several closed records can share an ID. Rejected exit
    attempts never produce one; they remain rejected envelopes in the log.
    """

    obligation_id: str
    open_seq: int
    exit_seq: int
    semantics: str
    min_eliminations: int
    progress_at_exit: int


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

    The last four fields are populated only by reducers that support
    reinstatement and stay empty under ``MaskMeetTombstoneReducer``:

    - ``asserted_pairs``: every ``(seq, hypothesis)`` an accepted
      elimination envelope asserted dead, whether or not the hypothesis
      was still a survivor at the time.
    - ``reinstated_pairs``: the subset of ``asserted_pairs`` voided by an
      accepted ``reinstate``. A hypothesis is eliminated iff it has at
      least one asserted pair not in this set.
    - ``key_seqs``: idempotency key to the seq of the accepted envelope
      that consumed it, so a probe can be reinstated by ``probe_id``.
    - ``closed_obligations``: frozen records of successful exits.
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
    asserted_pairs: frozenset[tuple[int, str]] = frozenset()
    reinstated_pairs: frozenset[tuple[int, str]] = frozenset()
    key_seqs: dict[str, int] = field(default_factory=dict)
    closed_obligations: tuple[ClosedObligation, ...] = ()

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

    @property
    def position_digest(self) -> str:
        """Session-independent identity of the current lattice position.

        Equal across sessions with the same survivors; unchanged by an op
        that eliminates nothing. See :func:`compute_position_digest`.
        """
        return compute_position_digest(self.survivors)

    def obligation(self, obligation_id: str) -> ObligationEntry | None:
        """Return the active obligation with this ID, or ``None``.

        Closed records are not searched; see ``closed_obligations``.
        """
        for entry in self.obligations:
            if entry.obligation_id == obligation_id:
                return entry
        return None

    def obligation_progress(self, obligation_id: str) -> int | None:
        """Progress of the active obligation under its own semantics, or
        ``None`` if no obligation with that ID is open."""
        entry = self.obligation(obligation_id)
        return None if entry is None else entry.progress(self.eliminated)

    @property
    def in_force_pairs(self) -> frozenset[tuple[int, str]]:
        """Asserted pairs not yet reinstated."""
        return self.asserted_pairs - self.reinstated_pairs

    def killers(self, hypothesis_id: str) -> frozenset[int]:
        """Seqs of the in-force elimination envelopes holding this
        hypothesis dead. Empty for survivors, and always empty under a
        reducer without reinstatement support."""
        return frozenset(s for s, h in self.in_force_pairs if h == hypothesis_id)

    def asserted_dead(self, seq: int) -> frozenset[str]:
        """Hypotheses the envelope at ``seq`` asserted dead, reinstated or
        not. Empty if that envelope was not an accepted elimination."""
        return frozenset(h for s, h in self.asserted_pairs if s == seq)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "seq": self.seq,
            "state_hash": self.state_hash,
            "position_digest": self.position_digest,
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
                    "open_seq": o.open_seq,
                    "semantics": o.semantics,
                    "dead_at_open": sorted(o.dead_at_open),
                    "progress": o.progress(self.eliminated),
                }
                for o in self.obligations
            ],
            "active_obligations": sorted(self.active_obligations),
            "closed_obligations": [
                {
                    "obligation_id": c.obligation_id,
                    "open_seq": c.open_seq,
                    "exit_seq": c.exit_seq,
                    "semantics": c.semantics,
                    "min_eliminations": c.min_eliminations,
                    "progress_at_exit": c.progress_at_exit,
                }
                for c in self.closed_obligations
            ],
            "conclusion_history": list(self.conclusion_history),
            "terminated": self.terminated,
            "attrs": dict(self.attrs),
            "stability_window": self.stability_window,
            "asserted_pairs": sorted([s, h] for s, h in self.asserted_pairs),
            "reinstated_pairs": sorted([s, h] for s, h in self.reinstated_pairs),
            "key_seqs": dict(sorted(self.key_seqs.items())),
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
class ReinstateResult:
    """Outcome of ``Session.reinstate`` / ``Session.reinstate_probe``.

    ``voided`` is the set of hypotheses whose elimination by the target
    envelope was voided; ``revived`` is the subset that returned to the
    survivor set because no other in-force elimination still held it.
    """

    accepted: bool
    error: str | None = None
    voided: frozenset[str] = frozenset()
    revived: frozenset[str] = frozenset()


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
