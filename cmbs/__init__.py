"""
CMBS v0 Core.

CMBS is a belief-state accounting system. It tracks hypotheses, eliminations,
entropy, and obligation discipline. It does not select probes, interpret
observables, or manage workflows. Semantics live in adapters.
"""

from .adapters.legacy import (
    LegacyEliminationEvent,
    LegacyReplayAdapter,
    submit_legacy_elimination,
)
from .belief_server import (
    AuditEntry,
    BeliefServer,
    BeliefSnapshot,
    OntologyBundle,
)
from .belief_state import BeliefState
from .core import (
    CMBSCore,
    EliminationEvent,
    ObligationExitResult,
    ProbeResult,
    TerminationResult,
)
from .op_models import BranchRecord, OperationEnvelope, OperationSpec, SessionRecord
from .oplog_server import OpAppendResult, OplogServer, OplogServerError
from .spi import (
    EliminationProvenance,
    EliminationResult,
    EliminationStore,
    HypothesisProvider,
    RecoveredState,
    discover_providers,
)
from .stores import InMemoryStore

__all__ = [
    "CMBSCore",
    "EliminationEvent",
    "ObligationExitResult",
    "ProbeResult",
    "TerminationResult",
    "AuditEntry",
    "BeliefServer",
    "BeliefSnapshot",
    "OntologyBundle",
    "BeliefState",
    "OperationSpec",
    "OperationEnvelope",
    "BranchRecord",
    "SessionRecord",
    "OplogServer",
    "OplogServerError",
    "OpAppendResult",
    "EliminationProvenance",
    "EliminationResult",
    "EliminationStore",
    "HypothesisProvider",
    "RecoveredState",
    "discover_providers",
    "InMemoryStore",
    "LegacyEliminationEvent",
    "LegacyReplayAdapter",
    "submit_legacy_elimination",
]
