"""
Reducer protocol and the shipped reducer for the unified Session kernel.

A reducer maps an ordered prefix of the op log to a ``Snapshot``. The kernel
holds no mutable state of its own — state is always ``reduce(initial_hypotheses,
log_prefix)``. This makes replay deterministic and gives every envelope a
verifiable "the state after this op" hash.

The shipped reducer, ``MaskMeetTombstoneReducer``, also enforces the
workflow invariants (INV-2, INV-3, INV-6) by rejecting ops at reduce time
rather than letting them mutate state. INV-5a (entropy) is a derived
property computed on the resulting snapshot, never used as a gate.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from .operations import OperationEnvelope
from .snapshot import Snapshot


@runtime_checkable
class Reducer(Protocol):
    """Maps initial hypotheses + accepted ops to a snapshot."""

    version: str

    def reduce(
        self,
        initial_hypotheses: Iterable[str],
        accepted_ops: Iterable[OperationEnvelope],
    ) -> Snapshot:
        """Compute the snapshot resulting from applying ``accepted_ops``
        in order to a session initialized with ``initial_hypotheses``."""
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


class MaskMeetTombstoneReducer:
    """The shipped reducer.

    Semantics (replay-versioned as ``"v1_mask_meet_tombstone"``):

    - ``probe_result``: monotone elimination by ID set; rejects if the
      ``op_id`` was already consumed (INV-3 enforcement).
    - ``enter_obligation``: registers an obligation with a minimum
      elimination count.
    - ``exit_obligation``: permitted iff the obligation's min has been
      met *within scope* — i.e., counted only eliminations recorded after
      the matching ``enter_obligation`` (INV-6 enforcement).
    - ``declare_conclusion``: records a conclusion in stability history.
    - ``request_termination``: permitted iff the stability window is
      satisfied (INV-2 enforcement). Window of 0 disables the gate.
    - Unknown op_types are recorded but produce no state change.

    Rejected ops still enter the op log (with ``accepted=False`` and a
    ``rejected_reason``) — every probe outcome, including 0-IG and
    rejected attempts, is part of the audit trail.
    """

    version: str = "v1_mask_meet_tombstone"

    def reduce(
        self,
        initial_hypotheses: Iterable[str],
        accepted_ops: Iterable[OperationEnvelope],
    ) -> Snapshot:
        raise NotImplementedError("MaskMeetTombstoneReducer.reduce")

    def classify(self, envelope_kind: str) -> str:
        raise NotImplementedError("MaskMeetTombstoneReducer.classify")
