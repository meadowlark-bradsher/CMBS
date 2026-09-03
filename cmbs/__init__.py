"""
CMBS — Constraint Mask Belief System.

CMBS is a belief-state accounting system. One ``Session`` is one
investigation: it tracks hypotheses, records eliminations as an append-only
op log, computes entropy, and enforces obligation discipline. It does not
select probes, interpret observables, or manage workflows. Semantics live in
adapters.

    from cmbs import Session

    session = Session(hypothesis_ids={"H1", "H2", "H3"})
    session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
    assert session.survivors == {"H2", "H3"}

See ``design/adr-001-unify-kernels.md`` and ``design/adr-002-naming.md``.
"""

from .adapters.legacy import (
    LegacyEliminationEvent,
    LegacyReplayAdapter,
    submit_legacy_elimination,
)
from .operations import AppendResult, OperationEnvelope, OperationSpec
from .reducer import MaskMeetTombstoneReducer, Reducer, compute_state_hash
from .session import Session
from .snapshot import (
    ObligationEntry,
    ObligationExitResult,
    OntologyBundle,
    ProbeResult,
    Snapshot,
    TerminationResult,
)
from .spi import HypothesisProvider, discover_providers
from .store import InMemoryOpLogStore, OpLogStore, RecoveredSession

__all__ = [
    # kernel
    "Session",
    "Snapshot",
    "ObligationEntry",
    "OntologyBundle",
    # operations
    "OperationSpec",
    "OperationEnvelope",
    "AppendResult",
    # reducer
    "Reducer",
    "MaskMeetTombstoneReducer",
    "compute_state_hash",
    # persistence
    "OpLogStore",
    "InMemoryOpLogStore",
    "RecoveredSession",
    # facade results
    "ProbeResult",
    "ObligationExitResult",
    "TerminationResult",
    # SPI
    "HypothesisProvider",
    "discover_providers",
    # legacy replay
    "LegacyEliminationEvent",
    "LegacyReplayAdapter",
    "submit_legacy_elimination",
]
