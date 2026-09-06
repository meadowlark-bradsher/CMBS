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

import copy
import time
import uuid
from collections.abc import Iterable

from .operations import AppendResult, OperationEnvelope, OperationSpec
from .reducer import MaskMeetTombstoneReducer, Reducer
from .snapshot import (
    ObligationExitResult,
    OntologyBundle,
    ProbeResult,
    Snapshot,
    TerminationResult,
)
from .store import InMemoryOpLogStore, OpLogStore


class Session:
    """One investigation. State = ``reduce(initial_hypotheses, op_log)``.

    Constructed directly with an initial hypothesis universe; persists to
    the supplied ``store`` (in-memory by default). Recovered later via
    :meth:`Session.recover`.

    The session is single-purpose: one universe, one log, one terminal
    state. To run multiple investigations in parallel, create multiple
    Session instances.

    The session is the single writer to its log. It keeps the current
    snapshot cached and advances it one ``apply`` step per append; the
    cached snapshot is always equal to a full ``reduce`` of the log.
    """

    def __init__(
        self,
        hypothesis_ids: Iterable[str],
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
        universe = frozenset(hypothesis_ids)
        for hid in universe:
            if not isinstance(hid, str):
                raise TypeError(f"hypothesis IDs must be strings, got {hid!r}")
        if isinstance(stability_window, bool) or not isinstance(stability_window, int):
            raise TypeError("stability_window must be an int")
        if stability_window < 0:
            raise ValueError("stability_window must be >= 0")

        self._session_id = session_id if session_id is not None else str(uuid.uuid4())
        self._initial = universe
        self._ontology = ontology
        self._stability_window = stability_window
        self._reducer: Reducer = reducer if reducer is not None else MaskMeetTombstoneReducer()
        self._store: OpLogStore = store if store is not None else InMemoryOpLogStore()

        self._store.create_session(
            self._session_id,
            universe,
            ontology,
            stability_window,
            self._reducer.version,
        )
        self._snapshot: Snapshot = self._reducer.initial(
            self._session_id, universe, stability_window=stability_window
        )
        self._op_ids: set[str] = set()

    # ------------------------------------------------------------------
    # Imperative facade — common cases
    # ------------------------------------------------------------------

    def submit_probe_result(
        self,
        probe_id: str,
        observable_id: str,
        eliminated: Iterable[str],
        *,
        source_id: str = "",
        provenance: dict | None = None,
    ) -> ProbeResult:
        """Submit a probe outcome.

        Translates to an envelope of ``op_type="probe_result"`` with
        ``payload`` carrying ``observable_id``, ``eliminate``, and any
        opaque ``provenance`` dict. ``probe_id`` becomes the envelope's
        ``idempotency_key`` — re-submission of the same ``probe_id`` is
        rejected by the reducer and logged as a rejected envelope, with
        no state change (INV-3 enforcement).

        Empty ``eliminated`` is recorded normally; the envelope enters
        the audit log with ``eliminate=[]``, and any active obligation
        increments its in-scope count by 0. The audit reflects that the
        probe happened.
        """
        if not isinstance(probe_id, str):
            raise TypeError("probe_id must be a string")
        requested = frozenset(eliminated)
        payload: dict = {
            "observable_id": observable_id,
            "eliminate": sorted(requested),
        }
        if provenance is not None:
            payload["provenance"] = dict(provenance)

        before = self._snapshot
        result = self.append(
            OperationSpec(
                op_type="probe_result",
                payload=payload,
                source_id=source_id,
                idempotency_key=probe_id,
            )
        )
        if not result.envelope.accepted:
            return ProbeResult(accepted=False, error=result.envelope.rejected_reason)
        return ProbeResult(
            accepted=True,
            eliminated=requested & before.survivors,
            already_eliminated=requested & before.eliminated,
        )

    def enter_obligation(
        self,
        obligation_id: str,
        min_eliminations: int = 1,
        *,
        source_id: str = "",
    ) -> AppendResult:
        """Open an obligation requiring at least ``min_eliminations``
        eliminations within scope before it can be exited (INV-6).
        Adapter-initiated; the kernel never opens obligations
        automatically.

        Returns the append result so the caller can see whether the entry
        was accepted (it is rejected if ``obligation_id`` is already open).
        """
        return self.append(
            OperationSpec(
                op_type="enter_obligation",
                payload={
                    "obligation_id": obligation_id,
                    "min_eliminations": min_eliminations,
                },
                source_id=source_id,
            )
        )

    def request_obligation_exit(
        self,
        obligation_id: str,
        *,
        source_id: str = "",
    ) -> ObligationExitResult:
        """Request to close ``obligation_id``. Permitted only if its
        in-scope elimination count has met or exceeded its
        ``min_eliminations`` (INV-6)."""
        result = self.append(
            OperationSpec(
                op_type="exit_obligation",
                payload={"obligation_id": obligation_id},
                source_id=source_id,
            )
        )
        return ObligationExitResult(
            permitted=result.envelope.accepted,
            error=result.envelope.rejected_reason,
        )

    def declare_conclusion(
        self,
        conclusion_id: str,
        *,
        source_id: str = "",
    ) -> AppendResult:
        """Record a current conclusion. Used by the stability window
        check; the kernel does not interpret conclusion meaning."""
        return self.append(
            OperationSpec(
                op_type="declare_conclusion",
                payload={"conclusion_id": conclusion_id},
                source_id=source_id,
            )
        )

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
        result = self.append(
            OperationSpec(op_type="request_termination", payload={}, source_id=source_id)
        )
        return TerminationResult(
            permitted=result.envelope.accepted,
            error=result.envelope.rejected_reason,
        )

    # ------------------------------------------------------------------
    # Lower-level append API
    # ------------------------------------------------------------------

    def append(self, spec: OperationSpec) -> AppendResult:
        """Append an arbitrary operation envelope.

        The reducer determines whether the op is accepted or rejected;
        either way the envelope enters the log. Returns the persisted
        envelope plus the post-state hash and survivor count.

        Two dedupe mechanisms apply, with different meanings:

        - A caller-supplied ``op_id`` that is already in the log is a
          transport-level retry. Nothing is appended; the original
          envelope and the state hash at its position are returned.
        - An ``idempotency_key`` already consumed by an accepted op is a
          domain-level repeat (INV-3). A new, *rejected* envelope is
          appended so the attempt is auditable.
        """
        if not isinstance(spec, OperationSpec):
            raise TypeError("append expects an OperationSpec")
        if not isinstance(spec.op_type, str) or not spec.op_type:
            raise ValueError("op_type must be a non-empty string")

        if spec.op_id is not None and spec.op_id in self._op_ids:
            return self._result_for_existing(spec.op_id)

        accepted, reason = self._reducer.check(self._snapshot, spec)
        envelope = OperationEnvelope(
            op_id=spec.op_id if spec.op_id is not None else str(uuid.uuid4()),
            seq=self._snapshot.seq + 1,
            op_type=spec.op_type,
            payload=copy.deepcopy(dict(spec.payload or {})),
            source_id=spec.source_id,
            idempotency_key=spec.idempotency_key,
            accepted=accepted,
            rejected_reason=reason,
            created_at=time.time(),
        )
        self._store.append(self._session_id, envelope)
        self._snapshot = self._reducer.apply(self._snapshot, envelope)
        self._op_ids.add(envelope.op_id)
        return AppendResult(
            envelope=envelope,
            state_hash_after=self._snapshot.state_hash,
            survivors_count_after=self._snapshot.n_survivors,
        )

    def _result_for_existing(self, op_id: str) -> AppendResult:
        ops = self._store.read_ops(self._session_id)
        for envelope in ops:
            if envelope.op_id == op_id:
                state = self._reducer.reduce(
                    self._initial,
                    ops[: envelope.seq],
                    session_id=self._session_id,
                    stability_window=self._stability_window,
                )
                return AppendResult(
                    envelope=envelope,
                    state_hash_after=state.state_hash,
                    survivors_count_after=state.n_survivors,
                )
        raise RuntimeError(f"op_id {op_id!r} indexed but not found in store")  # pragma: no cover

    # ------------------------------------------------------------------
    # Read access
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def ontology(self) -> OntologyBundle | None:
        return self._ontology

    @property
    def stability_window(self) -> int:
        return self._stability_window

    @property
    def reducer(self) -> Reducer:
        return self._reducer

    @property
    def initial_hypotheses(self) -> frozenset[str]:
        """The universe this session was created with."""
        return self._initial

    @property
    def survivors(self) -> frozenset[str]:
        """Currently surviving hypothesis IDs."""
        return self._snapshot.survivors

    @property
    def entropy(self) -> float:
        """``log₂(|survivors|)``; 0.0 if ≤1 survivor (INV-5a)."""
        return self._snapshot.entropy

    @property
    def consumed_probes(self) -> frozenset[str]:
        """Idempotency keys consumed by accepted ops. The facade populates
        this with ``probe_id`` values; callers of ``append`` who supply
        their own keys will see those here too."""
        return self._snapshot.consumed_op_ids

    @property
    def active_obligations(self) -> frozenset[str]:
        """Currently open obligation IDs."""
        return self._snapshot.active_obligations

    @property
    def is_terminated(self) -> bool:
        """Whether ``request_termination`` has succeeded for this session."""
        return self._snapshot.terminated

    @property
    def position_digest(self) -> str:
        """Session-independent identity of the current survivor set.
        See :func:`cmbs.snapshot.compute_position_digest`."""
        return self._snapshot.position_digest

    @property
    def head_seq(self) -> int:
        """Seq of the last envelope in the log (0 if empty)."""
        return self._snapshot.seq

    def snapshot(self) -> Snapshot:
        """Return an immutable view of the current state."""
        return self._snapshot

    def operations(
        self,
        from_seq: int | None = None,
        to_seq: int | None = None,
    ) -> tuple[OperationEnvelope, ...]:
        """Return persisted envelopes in the inclusive seq range."""
        return self._store.read_ops(self._session_id, from_seq, to_seq)

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
        """Reconstitute a session from its persisted op log.

        The store records which reducer version wrote the log; replaying
        under a different version would silently change meaning, so a
        mismatch raises ``ValueError``.
        """
        record = store.recover(session_id)
        active: Reducer = reducer if reducer is not None else MaskMeetTombstoneReducer()
        if active.version != record.reducer_version:
            raise ValueError(
                f"Session {session_id!r} was written under reducer "
                f"{record.reducer_version!r}; cannot replay under {active.version!r}."
            )

        session = cls.__new__(cls)
        session._session_id = record.session_id
        session._initial = frozenset(record.initial_hypotheses)
        session._ontology = record.ontology
        session._stability_window = record.stability_window
        session._reducer = active
        session._store = store
        session._snapshot = active.reduce(
            session._initial,
            record.envelopes,
            session_id=record.session_id,
            stability_window=record.stability_window,
        )
        session._op_ids = {envelope.op_id for envelope in record.envelopes}
        return session
