"""
Reducer protocol and the shipped reducer for the unified Session kernel.

A reducer maps an ordered prefix of the op log to a ``Snapshot``. The kernel
holds no mutable state of its own — state is always ``reduce(initial_hypotheses,
log_prefix)``. This makes replay deterministic and gives every envelope a
verifiable "the state after this op" hash.

The shipped reducer, ``MaskMeetTombstoneReducer``, also enforces the
workflow invariants (INV-2, INV-3, INV-6) by rejecting ops at check time
rather than letting them mutate state. INV-5a (entropy) is a derived
property computed on the resulting snapshot, never used as a gate.

A reducer exposes three primitives plus the fold built from them:

- ``initial(...)``: the seq-0 snapshot for a fresh universe.
- ``check(snapshot, spec)``: the acceptance verdict for a submitted op
  against the current snapshot. Called once, at append time; the verdict
  is persisted on the envelope.
- ``apply(snapshot, envelope)``: one step of the fold. Rejected envelopes
  only advance ``seq`` (and therefore the hash); accepted ones mutate.
- ``reduce(initial_hypotheses, ops)``: ``initial`` folded through ``apply``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import replace
from typing import Any, Protocol, runtime_checkable

from .operations import OperationEnvelope, OperationSpec
from .snapshot import (
    OBLIGATION_NET,
    OBLIGATION_SEMANTICS,
    ClosedObligation,
    ObligationEntry,
    Snapshot,
)

# Canonical op categories returned by ``Reducer.classify``.
KIND_ELIMINATION = "elimination"
KIND_REINSTATEMENT = "reinstatement"
KIND_OBLIGATION = "obligation"
KIND_CONCLUSION = "conclusion"
KIND_TERMINATION = "termination"
KIND_UNKNOWN = "unknown"


@runtime_checkable
class Reducer(Protocol):
    """Maps initial hypotheses + an op log to a snapshot."""

    version: str

    def initial(
        self,
        session_id: str,
        hypothesis_ids: Iterable[str],
        *,
        stability_window: int = 0,
    ) -> Snapshot:
        """The seq-0 snapshot of a fresh session."""
        ...

    def check(
        self,
        snapshot: Snapshot,
        spec: OperationSpec,
    ) -> tuple[bool, str | None]:
        """Decide whether ``spec`` is accepted against ``snapshot``.

        Returns ``(accepted, rejected_reason)``; ``rejected_reason`` is
        ``None`` iff accepted.
        """
        ...

    def apply(
        self,
        snapshot: Snapshot,
        envelope: OperationEnvelope,
    ) -> Snapshot:
        """Fold one persisted envelope into ``snapshot``.

        Must advance ``seq`` to ``envelope.seq`` and recompute the hash for
        every envelope, accepted or not, so that a snapshot always names
        its log position.
        """
        ...

    def reduce(
        self,
        initial_hypotheses: Iterable[str],
        ops: Iterable[OperationEnvelope],
        *,
        session_id: str = "",
        stability_window: int = 0,
    ) -> Snapshot:
        """Compute the snapshot resulting from applying ``ops`` in order to
        a session initialized with ``initial_hypotheses``."""
        ...

    def classify(
        self,
        envelope_kind: str,
    ) -> str:
        """Return the canonical category of an op_type as seen by this reducer.

        Used for tests and tooling that want to know whether an op is an
        elimination, an obligation event, etc. without re-implementing the
        reducer's logic.
        """
        ...


def compute_state_hash(snapshot: Snapshot, reducer_version: str) -> str:
    """SHA-256 over the snapshot's canonical content, the reducer version,
    the session ID, and the log position.

    Two snapshots hash equal iff they describe the same belief state at the
    same position of the same session under the same reducer. The hash
    does **not** include ``snapshot.state_hash`` itself.

    Fields that only a reinstatement-aware reducer populates enter the
    hashed content only when non-empty, and an obligation's extended
    fields only when it carries an ``open_seq``. Hashes computed under
    ``MaskMeetTombstoneReducer`` are therefore byte-identical to those of
    earlier releases.
    """
    content: dict[str, Any] = {
        "survivors": sorted(snapshot.survivors),
        "eliminated": sorted(snapshot.eliminated),
        "consumed_op_ids": sorted(snapshot.consumed_op_ids),
        "obligations": [_obligation_content(o) for o in snapshot.obligations],
        "conclusion_history": list(snapshot.conclusion_history),
        "terminated": snapshot.terminated,
        "stability_window": snapshot.stability_window,
        "attrs": _canonicalize(snapshot.attrs),
    }
    if snapshot.asserted_pairs:
        content["asserted_pairs"] = sorted([s, h] for s, h in snapshot.asserted_pairs)
    if snapshot.reinstated_pairs:
        content["reinstated_pairs"] = sorted([s, h] for s, h in snapshot.reinstated_pairs)
    if snapshot.key_seqs:
        content["key_seqs"] = sorted([k, v] for k, v in snapshot.key_seqs.items())
    if snapshot.closed_obligations:
        content["closed_obligations"] = [
            [
                c.obligation_id,
                c.open_seq,
                c.exit_seq,
                c.semantics,
                c.min_eliminations,
                c.progress_at_exit,
            ]
            for c in snapshot.closed_obligations
        ]
    body = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload = "|".join([body, reducer_version, snapshot.session_id, str(snapshot.seq)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _obligation_content(entry: ObligationEntry) -> list[Any]:
    base: list[Any] = [entry.obligation_id, entry.min_eliminations, entry.eliminations_in_scope]
    if entry.open_seq:
        base.extend([entry.open_seq, entry.semantics, sorted(entry.dead_at_open)])
    return base


# ----------------------------------------------------------------------
# Version registry
# ----------------------------------------------------------------------

_REGISTRY: dict[str, type[Reducer]] = {}


def register_reducer(cls: type[Reducer]) -> type[Reducer]:
    """Class decorator: make ``cls`` recoverable by its ``version`` string."""
    _REGISTRY[cls.version] = cls
    return cls


def reducer_for_version(version: str) -> Reducer:
    """Instantiate the registered reducer for ``version``.

    Raises ``ValueError`` naming the known versions if none is registered,
    so ``Session.recover`` can refuse a log it would silently misread.
    """
    try:
        cls = _REGISTRY[version]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise ValueError(
            f"no reducer registered for version {version!r}; known versions: {known}. "
            "Pass reducer=... explicitly."
        ) from None
    return cls()


def registered_reducer_versions() -> tuple[str, ...]:
    """The version strings ``reducer_for_version`` knows."""
    return tuple(sorted(_REGISTRY))


@register_reducer
class MaskMeetTombstoneReducer:
    """The shipped reducer.

    Semantics (replay-versioned as ``"v1_mask_meet_tombstone"``):

    - Any op carrying an ``idempotency_key`` already consumed by an accepted
      op is rejected (INV-3 enforcement). The facade uses ``probe_id`` as
      the key of ``probe_result`` ops, so a repeated probe is rejected and
      the attempt is still logged.
    - ``probe_result`` / ``retract`` / ``tombstone``: monotone elimination
      by ID set (``payload["eliminate"]``).
    - ``assert`` / ``oracle_answer``: elimination plus ``payload["set"]``
      written into ``attrs``.
    - ``refine``: conditional elimination — applied iff
      ``attrs[payload["if_attr"]] == payload["equals"]``.
    - ``enter_obligation``: registers an obligation with a minimum
      elimination count. Rejected if that ID is already active.
    - ``exit_obligation``: permitted iff the obligation's min has been
      met *within scope* — i.e., counted only eliminations recorded after
      the matching ``enter_obligation`` (INV-6 enforcement).
    - ``declare_conclusion``: records a conclusion in stability history.
    - ``request_termination``: permitted iff the stability window is
      satisfied (INV-2 enforcement). Window of 0 disables the gate.
      Termination does not freeze the session; later ops still apply.
      This is provisional pending the termination-policy ADR.
    - Unknown op_types are accepted and produce no state change.

    Every newly eliminated hypothesis, whatever op removed it, counts
    toward every obligation open at the time.

    Rejected ops still enter the op log (with ``accepted=False`` and a
    ``rejected_reason``) — every probe outcome, including 0-IG and
    rejected attempts, is part of the audit trail.
    """

    version: str = "v1_mask_meet_tombstone"

    _ELIMINATION_OPS = frozenset(
        {"probe_result", "retract", "tombstone", "assert", "oracle_answer", "refine"}
    )
    _OBLIGATION_OPS = frozenset({"enter_obligation", "exit_obligation"})

    # ------------------------------------------------------------------
    # Protocol surface
    # ------------------------------------------------------------------

    def initial(
        self,
        session_id: str,
        hypothesis_ids: Iterable[str],
        *,
        stability_window: int = 0,
    ) -> Snapshot:
        snapshot = Snapshot(
            session_id=session_id,
            seq=0,
            state_hash="",
            survivors=frozenset(hypothesis_ids),
            eliminated=frozenset(),
            consumed_op_ids=frozenset(),
            obligations=(),
            conclusion_history=(),
            terminated=False,
            attrs={},
            stability_window=stability_window,
        )
        return self._hashed(snapshot)

    def check(self, snapshot: Snapshot, spec: OperationSpec) -> tuple[bool, str | None]:
        key = spec.idempotency_key
        if key is not None and key in snapshot.consumed_op_ids:
            return False, f"duplicate idempotency_key: {key!r}"

        payload = spec.payload or {}
        op_type = spec.op_type

        if op_type == "enter_obligation":
            obligation_id = payload.get("obligation_id")
            if not isinstance(obligation_id, str):
                return False, "enter_obligation requires a string obligation_id"
            if obligation_id in snapshot.active_obligations:
                return False, f"obligation already active: {obligation_id!r}"
            minimum = payload.get("min_eliminations", 1)
            if not _is_int(minimum) or minimum < 0:
                return False, "min_eliminations must be a non-negative integer"
            return True, None

        if op_type == "exit_obligation":
            obligation_id = payload.get("obligation_id")
            if not isinstance(obligation_id, str):
                return False, "exit_obligation requires a string obligation_id"
            entry = snapshot.obligation(obligation_id)
            if entry is None:
                return False, f"obligation not active: {obligation_id!r}"
            if entry.eliminations_in_scope < entry.min_eliminations:
                return False, (
                    f"insufficient eliminations in scope for {obligation_id!r}: "
                    f"{entry.eliminations_in_scope} of {entry.min_eliminations} required"
                )
            return True, None

        if op_type == "declare_conclusion":
            if not isinstance(payload.get("conclusion_id"), str):
                return False, "declare_conclusion requires a string conclusion_id"
            return True, None

        if op_type == "request_termination":
            window = snapshot.stability_window
            if window <= 0:
                return True, None
            history = snapshot.conclusion_history
            if len(history) < window:
                return False, (
                    f"conclusion history shorter than stability window: "
                    f"{len(history)} of {window} required"
                )
            if len(set(history[-window:])) != 1:
                return False, f"conclusion unstable over the last {window} declarations"
            return True, None

        if op_type in self._ELIMINATION_OPS:
            eliminate = payload.get("eliminate")
            if eliminate is not None and not isinstance(eliminate, list | tuple | set | frozenset):
                return False, "eliminate must be a collection of hypothesis IDs"
            return True, None

        return True, None

    def apply(self, snapshot: Snapshot, envelope: OperationEnvelope) -> Snapshot:
        if not envelope.accepted:
            return self._hashed(replace(snapshot, seq=envelope.seq))

        payload = envelope.payload or {}
        op_type = envelope.op_type

        survivors = set(snapshot.survivors)
        eliminated = set(snapshot.eliminated)
        consumed = set(snapshot.consumed_op_ids)
        obligations = list(snapshot.obligations)
        history = snapshot.conclusion_history
        terminated = snapshot.terminated
        attrs = dict(snapshot.attrs)

        if envelope.idempotency_key is not None:
            consumed.add(envelope.idempotency_key)

        if op_type in self._ELIMINATION_OPS:
            newly = self._eliminations(op_type, payload, survivors, attrs)
            survivors -= newly
            eliminated |= newly
            if newly:
                obligations = [
                    replace(o, eliminations_in_scope=o.eliminations_in_scope + len(newly))
                    for o in obligations
                ]
            set_fields = payload.get("set")
            if op_type in {"assert", "oracle_answer"} and isinstance(set_fields, dict):
                for k, v in set_fields.items():
                    attrs[str(k)] = v

        elif op_type == "enter_obligation":
            obligations.append(
                ObligationEntry(
                    obligation_id=payload["obligation_id"],
                    min_eliminations=int(payload.get("min_eliminations", 1)),
                    eliminations_in_scope=0,
                )
            )

        elif op_type == "exit_obligation":
            target = payload["obligation_id"]
            obligations = [o for o in obligations if o.obligation_id != target]

        elif op_type == "declare_conclusion":
            history = (*history, payload["conclusion_id"])

        elif op_type == "request_termination":
            terminated = True

        # Unknown op types: no state change beyond seq/consumed key.

        return self._hashed(
            Snapshot(
                session_id=snapshot.session_id,
                seq=envelope.seq,
                state_hash="",
                survivors=frozenset(survivors),
                eliminated=frozenset(eliminated),
                consumed_op_ids=frozenset(consumed),
                obligations=tuple(obligations),
                conclusion_history=history,
                terminated=terminated,
                attrs=attrs,
                stability_window=snapshot.stability_window,
            )
        )

    def reduce(
        self,
        initial_hypotheses: Iterable[str],
        ops: Iterable[OperationEnvelope],
        *,
        session_id: str = "",
        stability_window: int = 0,
    ) -> Snapshot:
        snapshot = self.initial(session_id, initial_hypotheses, stability_window=stability_window)
        for envelope in ops:
            snapshot = self.apply(snapshot, envelope)
        return snapshot

    def classify(self, envelope_kind: str) -> str:
        if envelope_kind in self._ELIMINATION_OPS:
            return KIND_ELIMINATION
        if envelope_kind in self._OBLIGATION_OPS:
            return KIND_OBLIGATION
        if envelope_kind == "declare_conclusion":
            return KIND_CONCLUSION
        if envelope_kind == "request_termination":
            return KIND_TERMINATION
        return KIND_UNKNOWN

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _hashed(self, snapshot: Snapshot) -> Snapshot:
        return replace(snapshot, state_hash=compute_state_hash(snapshot, self.version))

    @staticmethod
    def _eliminations(
        op_type: str,
        payload: dict[str, Any],
        survivors: set[str],
        attrs: dict[str, Any],
    ) -> set[str]:
        """Hypotheses this op newly removes from ``survivors``."""
        if op_type == "refine":
            key = payload.get("if_attr")
            if key is None or attrs.get(str(key)) != payload.get("equals"):
                return set()
        requested = set(_as_list(payload.get("eliminate")))
        return requested & survivors


@register_reducer
class ReinstatingMaskReducer(MaskMeetTombstoneReducer):
    """Reinstatement-aware sibling of ``MaskMeetTombstoneReducer``.

    Replay-versioned as ``"v2_mask_reinstate"``. It shares the v1 op
    vocabulary and invariant gates, and differs in these ways:

    - **Support sets.** Every accepted elimination envelope records the
      pair ``(seq, h)`` for each hypothesis it asserted dead — the
      requested set after any ``refine`` condition, restricted to the
      universe — whether or not ``h`` was still a survivor. A hypothesis
      is eliminated iff it has at least one such pair not yet reinstated.
      Reinstating one of two envelopes that both killed ``h`` leaves ``h``
      dead.
    - ``reinstate``: voids the in-force pairs of exactly one accepted
      elimination envelope, named by ``payload["seq"]`` or by
      ``payload["probe_id"]`` (the idempotency key it consumed). An
      optional ``payload["hypotheses"]`` restricts it to a subset, which
      must lie within that envelope's asserted set and must not already be
      reinstated. Reinstatement never touches ``attrs`` and never
      un-consumes an idempotency key.
    - ``enter_obligation`` accepts ``payload["semantics"]``: ``"gross"``
      counts newly removed hypotheses in scope and ignores reinstatement
      (the v1 behaviour); ``"net"`` (the default) measures
      ``|eliminated_now \\ eliminated_at_open|``. ``exit_obligation`` is
      gated on progress under the declared semantics, and a successful
      exit leaves a frozen ``ClosedObligation`` record on the snapshot.
    - The retired ``retract`` and ``tombstone`` op types, which meant
      "eliminate" under v1, are rejected with a reason rather than falling
      through as silent no-ops. Other unknown op types remain silent
      no-ops, as under v1.

    The monotone object under this reducer is the pair of record sets
    ``(asserted_pairs, reinstated_pairs)``, which only grow. The survivor
    set is a derived view of them and may grow or shrink; entropy is
    non-increasing only across segments with no accepted ``reinstate``.
    """

    version: str = "v2_mask_reinstate"

    _ELIMINATION_OPS = frozenset({"probe_result", "assert", "oracle_answer", "refine"})
    _RETIRED_OPS = frozenset({"retract", "tombstone"})

    # ------------------------------------------------------------------
    # Protocol surface
    # ------------------------------------------------------------------

    def check(self, snapshot: Snapshot, spec: OperationSpec) -> tuple[bool, str | None]:
        key = spec.idempotency_key
        if key is not None and key in snapshot.consumed_op_ids:
            return False, f"duplicate idempotency_key: {key!r}"

        payload = spec.payload or {}
        op_type = spec.op_type

        if op_type in self._RETIRED_OPS:
            return False, (
                f"op_type {op_type!r} is retired under reducer {self.version!r}: "
                "use an elimination op such as 'probe_result' to eliminate, "
                "or 'reinstate' to revive"
            )

        if op_type == "reinstate":
            _, _, error = self._resolve_reinstate(snapshot, payload)
            return (False, error) if error is not None else (True, None)

        if op_type == "enter_obligation":
            semantics = payload.get("semantics", OBLIGATION_NET)
            if semantics not in OBLIGATION_SEMANTICS:
                return False, (
                    f"semantics must be one of {sorted(OBLIGATION_SEMANTICS)}, got {semantics!r}"
                )
            return super().check(snapshot, spec)

        if op_type == "exit_obligation":
            obligation_id = payload.get("obligation_id")
            if not isinstance(obligation_id, str):
                return False, "exit_obligation requires a string obligation_id"
            entry = snapshot.obligation(obligation_id)
            if entry is None:
                return False, f"obligation not active: {obligation_id!r}"
            progress = entry.progress(snapshot.eliminated)
            if progress < entry.min_eliminations:
                return False, (
                    f"insufficient {entry.semantics} progress for {obligation_id!r}: "
                    f"{progress} of {entry.min_eliminations} required"
                )
            return True, None

        return super().check(snapshot, spec)

    def apply(self, snapshot: Snapshot, envelope: OperationEnvelope) -> Snapshot:
        if not envelope.accepted:
            return self._hashed(replace(snapshot, seq=envelope.seq))

        payload = envelope.payload or {}
        op_type = envelope.op_type

        universe = snapshot.survivors | snapshot.eliminated
        asserted_pairs = set(snapshot.asserted_pairs)
        reinstated_pairs = set(snapshot.reinstated_pairs)
        key_seqs = dict(snapshot.key_seqs)
        obligations = list(snapshot.obligations)
        closed = list(snapshot.closed_obligations)
        history = snapshot.conclusion_history
        terminated = snapshot.terminated
        attrs = dict(snapshot.attrs)

        if envelope.idempotency_key is not None:
            key_seqs[envelope.idempotency_key] = envelope.seq

        if op_type in self._ELIMINATION_OPS:
            # Same selection as v1, but against the universe: every
            # hypothesis the op asserts dead is recorded, not only those
            # still surviving.
            asserted = self._eliminations(op_type, payload, set(universe), attrs)
            newly = asserted & snapshot.survivors
            asserted_pairs |= {(envelope.seq, h) for h in asserted}
            if newly:
                obligations = [
                    replace(o, eliminations_in_scope=o.eliminations_in_scope + len(newly))
                    for o in obligations
                ]
            set_fields = payload.get("set")
            if op_type in {"assert", "oracle_answer"} and isinstance(set_fields, dict):
                for k, v in set_fields.items():
                    attrs[str(k)] = v

        elif op_type == "reinstate":
            _, pairs, _ = self._resolve_reinstate(snapshot, payload)
            reinstated_pairs |= pairs

        elif op_type == "enter_obligation":
            obligations.append(
                ObligationEntry(
                    obligation_id=payload["obligation_id"],
                    min_eliminations=int(payload.get("min_eliminations", 1)),
                    eliminations_in_scope=0,
                    open_seq=envelope.seq,
                    semantics=payload.get("semantics", OBLIGATION_NET),
                    dead_at_open=snapshot.eliminated,
                )
            )

        elif op_type == "exit_obligation":
            target = payload["obligation_id"]
            entry = snapshot.obligation(target)
            if entry is not None:  # always true for an accepted exit
                closed.append(
                    ClosedObligation(
                        obligation_id=entry.obligation_id,
                        open_seq=entry.open_seq,
                        exit_seq=envelope.seq,
                        semantics=entry.semantics,
                        min_eliminations=entry.min_eliminations,
                        progress_at_exit=entry.progress(snapshot.eliminated),
                    )
                )
            obligations = [o for o in obligations if o.obligation_id != target]

        elif op_type == "declare_conclusion":
            history = (*history, payload["conclusion_id"])

        elif op_type == "request_termination":
            terminated = True

        # Unknown op types: no state change beyond seq/consumed key.

        eliminated = frozenset(h for _, h in asserted_pairs - reinstated_pairs)
        return self._hashed(
            Snapshot(
                session_id=snapshot.session_id,
                seq=envelope.seq,
                state_hash="",
                survivors=universe - eliminated,
                eliminated=eliminated,
                consumed_op_ids=frozenset(key_seqs),
                obligations=tuple(obligations),
                conclusion_history=history,
                terminated=terminated,
                attrs=attrs,
                stability_window=snapshot.stability_window,
                asserted_pairs=frozenset(asserted_pairs),
                reinstated_pairs=frozenset(reinstated_pairs),
                key_seqs=key_seqs,
                closed_obligations=tuple(closed),
            )
        )

    def classify(self, envelope_kind: str) -> str:
        if envelope_kind == "reinstate":
            return KIND_REINSTATEMENT
        return super().classify(envelope_kind)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_reinstate(
        snapshot: Snapshot,
        payload: dict[str, Any],
    ) -> tuple[int | None, frozenset[tuple[int, str]], str | None]:
        """Resolve a ``reinstate`` payload against ``snapshot``.

        Returns ``(target_seq, pairs_to_void, error)``. ``error`` is the
        rejection reason, or ``None`` when the op is acceptable; ``check``
        and ``apply`` share this so the two can never disagree.
        """
        has_seq = "seq" in payload
        has_probe = "probe_id" in payload
        if has_seq == has_probe:
            return None, frozenset(), "reinstate requires exactly one of 'seq' or 'probe_id'"

        if has_probe:
            probe_id = payload["probe_id"]
            if not isinstance(probe_id, str):
                return None, frozenset(), "probe_id must be a string"
            seq = snapshot.key_seqs.get(probe_id)
            if seq is None:
                return None, frozenset(), (
                    f"unknown probe_id {probe_id!r}: no accepted envelope consumed it"
                )
        else:
            seq = payload["seq"]
            if not _is_int(seq):
                return None, frozenset(), "seq must be an integer"
            if not 1 <= seq <= snapshot.seq:
                return None, frozenset(), f"seq {seq} out of range [1, {snapshot.seq}]"

        asserted = snapshot.asserted_dead(seq)
        if not asserted:
            return seq, frozenset(), (
                f"seq {seq} is not an accepted elimination envelope "
                "(or asserted no hypotheses)"
            )
        in_force = asserted - frozenset(h for s, h in snapshot.reinstated_pairs if s == seq)

        if "hypotheses" in payload:
            subset = payload["hypotheses"]
            if not isinstance(subset, list | tuple | set | frozenset):
                return seq, frozenset(), "hypotheses must be a collection of hypothesis IDs"
            names = frozenset(subset)
            if not names:
                return seq, frozenset(), "hypotheses must not be empty when given"
            unknown = names - asserted
            if unknown:
                return seq, frozenset(), (
                    f"never asserted dead by seq {seq}: {sorted(map(str, unknown))}"
                )
            already = names - in_force
            if already:
                return seq, frozenset(), (
                    f"already reinstated from seq {seq}: {sorted(map(str, already))}"
                )
            targets = names
        else:
            if not in_force:
                return seq, frozenset(), f"seq {seq} is already fully reinstated"
            targets = in_force

        return seq, frozenset((seq, h) for h in targets), None


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set | frozenset):
        return list(value)
    return [value]


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): _canonicalize(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, list | tuple):
        return [_canonicalize(v) for v in value]
    if isinstance(value, set | frozenset):
        return sorted(_canonicalize(v) for v in value)
    return value
