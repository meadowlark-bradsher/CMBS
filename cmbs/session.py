"""
The unified CMBS Session kernel.

One ``Session`` instance is one investigation. State is derived from the
op log via a reducer; the kernel holds no mutable belief state of its own.

The class exposes both an **imperative facade** for common cases
(``submit_probe_result``, ``enter_obligation``, etc.) and a **lower-level
append API** (``append(OperationSpec)``) for callers who want to construct
envelopes directly.

See ``design/adr-001-unify-kernels.md`` and ``design/adr-002-naming.md``
for the rationale behind this shape.
"""

from __future__ import annotations

from .operations import AppendResult, OperationSpec
from .reducer import Reducer
from .snapshot import (
    ObligationExitResult,
    OntologyBundle,
    ProbeResult,
    Snapshot,
    TerminationResult,
)
from .store import OpLogStore


class Session:
    """One investigation. State = ``reduce(initial_hypotheses, op_log)``.

    Constructed directly with an initial hypothesis universe; persists to
    the supplied ``store`` (in-memory by default). Recovered later via
    :meth:`Session.recover`.

    The session is single-purpose: one universe, one log, one terminal
    state. To run multiple investigations in parallel, create multiple
    Session instances.
    """

    def __init__(
        self,
        hypothesis_ids: set[str] | frozenset[str],
        *,
        ontology: OntologyBundle | None = None,
        reducer: Reducer | None = None,
        store: OpLogStore | None = None,
        stability_window: int = 0,
        session_id: str | None = None,
    ) -> None:
        """Create a new session.

        :param hypothesis_ids: initial set of opaque hypothesis IDs.
        :param ontology: optional versioned reference to hypothesis space
            and causal graph. Stored alongside the session for audit;
            never interpreted by the kernel.
        :param reducer: reducer implementation. Defaults to
            :class:`MaskMeetTombstoneReducer`.
        :param store: persistence backend. Defaults to a fresh
            :class:`InMemoryOpLogStore`.
        :param stability_window: number of consecutive identical
            conclusions required before ``request_termination`` succeeds.
            ``0`` disables INV-2 (default).
        :param session_id: optional caller-supplied ID. A UUID is
            generated if omitted.
        """
        raise NotImplementedError("Session.__init__")

    # ------------------------------------------------------------------
    # Imperative facade — common cases
    # ------------------------------------------------------------------

    def submit_probe_result(
        self,
        probe_id: str,
        observable_id: str,
        eliminated: set[str] | frozenset[str],
        *,
        source_id: str = "",
        provenance: dict | None = None,
    ) -> ProbeResult:
        """Submit a probe outcome.

        Translates to an envelope of ``op_type="probe_result"`` with
        ``payload`` carrying ``observable_id``, ``eliminate``, and any
        opaque ``provenance`` dict. ``probe_id`` becomes the envelope's
        ``idempotency_key`` — re-submission of the same ``probe_id``
        returns the previous result without mutating state (INV-3
        enforcement).

        Empty ``eliminated`` is recorded normally; the envelope enters
        the audit log with ``eliminate=[]``, and any active obligation
        increments its in-scope count by 0. The audit reflects that the
        probe happened.
        """
        raise NotImplementedError

    def enter_obligation(
        self,
        obligation_id: str,
        min_eliminations: int = 1,
        *,
        source_id: str = "",
    ) -> None:
        """Open an obligation requiring at least ``min_eliminations``
        eliminations within scope before it can be exited (INV-6).
        Adapter-initiated; the kernel never opens obligations
        automatically."""
        raise NotImplementedError

    def request_obligation_exit(
        self,
        obligation_id: str,
        *,
        source_id: str = "",
    ) -> ObligationExitResult:
        """Request to close ``obligation_id``. Permitted only if its
        in-scope elimination count has met or exceeded its
        ``min_eliminations`` (INV-6)."""
        raise NotImplementedError

    def declare_conclusion(
        self,
        conclusion_id: str,
        *,
        source_id: str = "",
    ) -> None:
        """Record a current conclusion. Used by the stability window
        check; the kernel does not interpret conclusion meaning."""
        raise NotImplementedError

    def request_termination(
        self,
        *,
        source_id: str = "",
    ) -> TerminationResult:
        """Request termination. Permitted iff either:

        - the configured stability window is 0 (disabled), or
        - the last N declared conclusions are identical, where N is the
          stability window (INV-2).

        Does **not** require singleton survivors, low entropy, or all
        obligations closed — those are policy choices left to the caller.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Lower-level append API
    # ------------------------------------------------------------------

    def append(self, spec: OperationSpec) -> AppendResult:
        """Append an arbitrary operation envelope.

        The reducer determines whether the op is accepted or rejected;
        either way the envelope enters the log. Returns the persisted
        envelope plus the post-state hash and survivor count.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Read access
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str:
        raise NotImplementedError

    @property
    def survivors(self) -> frozenset[str]:
        """Currently surviving hypothesis IDs."""
        raise NotImplementedError

    @property
    def entropy(self) -> float:
        """``log₂(|survivors|)``; 0.0 if ≤1 survivor (INV-5a)."""
        raise NotImplementedError

    @property
    def consumed_probes(self) -> frozenset[str]:
        """Set of ``probe_id`` values already submitted."""
        raise NotImplementedError

    @property
    def active_obligations(self) -> frozenset[str]:
        """Currently open obligation IDs."""
        raise NotImplementedError

    @property
    def is_terminated(self) -> bool:
        """Whether ``request_termination`` has succeeded for this session."""
        raise NotImplementedError

    def snapshot(self) -> Snapshot:
        """Return an immutable view of the current state."""
        raise NotImplementedError

    def operations(
        self,
        from_seq: int | None = None,
        to_seq: int | None = None,
    ) -> tuple:
        """Return persisted envelopes in the inclusive seq range."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    @classmethod
    def recover(
        cls,
        store: OpLogStore,
        session_id: str,
        *,
        reducer: Reducer | None = None,
    ) -> Session:
        """Reconstitute a session from its persisted op log."""
        raise NotImplementedError
