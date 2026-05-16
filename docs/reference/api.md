# API Reference

The public surface is re-exported from the top-level `cmbs` package. This page
covers the most useful symbols; the source files are the authoritative
reference.

## CMBSCore

The kernel. Pure Python, no I/O, no persistence.

```python
from cmbs import CMBSCore

core = CMBSCore(
    hypothesis_ids={"H1", "H2", "H3"},
    stability_window=0,   # 0 disables INV-2; positive N requires N consecutive identical conclusions
)
```

### Properties

| Property              | Type       | Description                                                 |
| --------------------- | ---------- | ----------------------------------------------------------- |
| `survivors`           | `Set[str]` | Currently surviving hypothesis IDs                          |
| `entropy`             | `float`    | `log₂(\|survivors\|)`; `0.0` if `\|survivors\| <= 1`         |
| `consumed_probes`     | `Set[str]` | Probe IDs already submitted                                 |
| `active_obligations`  | `Set[str]` | Currently open obligation IDs                               |
| `is_terminated`       | `bool`     | Whether `request_termination` has succeeded                 |

### Methods

| Method                                                            | Returns                  | Notes                                              |
| ----------------------------------------------------------------- | ------------------------ | -------------------------------------------------- |
| `submit_probe_result(probe_id, observable_id, eliminated)`        | `ProbeResult`            | Rejects duplicate `probe_id` (INV-3)               |
| `enter_obligation(obligation_id, min_eliminations=1)`             | `None`                   | Adapter-initiated; core never self-opens           |
| `request_obligation_exit(obligation_id)`                          | `ObligationExitResult`   | Permitted only after `min_eliminations` within scope (INV-6) |
| `is_obligation_active(obligation_id)`                             | `bool`                   |                                                    |
| `declare_conclusion(conclusion_id)`                               | `None`                   | Recorded for stability tracking                    |
| `request_termination()`                                           | `TerminationResult`      | Gated by stability window when enabled             |
| `get_elimination_history()`                                       | `List[EliminationEvent]` | Ordered audit trail                                |
| `serialize()`                                                     | `dict`                   | Checkpointable state                               |
| `CMBSCore.deserialize(state)`                                     | `CMBSCore`               | Restore from checkpoint                            |

### Result types

```python
@dataclass class ProbeResult:          accepted: bool;  error: Optional[str]
@dataclass class ObligationExitResult: permitted: bool; error: Optional[str]
@dataclass class TerminationResult:    permitted: bool; error: Optional[str]
@dataclass class EliminationEvent:     probe_id: str; observable_id: str; eliminated: Set[str]
```

## BeliefServer

A session-managing wrapper around `CMBSCore` that adds ontology bundles,
structured audit entries with before/after hashes, and a hypothesis-provider
plugin point. Suitable when you need to serve multiple parallel sessions
in-process.

```python
from cmbs import BeliefServer, OntologyBundle

server = BeliefServer()
```

Key types: `BeliefServer`, `BeliefSnapshot`, `OntologyBundle`, `AuditEntry`.
See [cmbs/belief_server.py](https://github.com/meadowlark-bradsher/CMBS/blob/main/cmbs/belief_server.py)
for the full surface.

## OplogServer (v2)

An alternative session model where state is always derived from a reducer
applied to an ordered prefix of an append-only operator log:

```
state = reduce(reducer_version, op_log_prefix(branch, seq))
```

Supports explicit branching, idempotency keys, and rejects non-commutative
merges with `409 NON_COMMUTATIVE_CONFLICT`. Use this when you need to explore
alternative operation orderings or replay deterministically.

```python
from cmbs import OplogServer
server = OplogServer()
```

Key types: `OplogServer`, `OperationSpec`, `OperationEnvelope`, `BranchRecord`,
`SessionRecord`, `OpAppendResult`. See
[cmbs/oplog_server.py](https://github.com/meadowlark-bradsher/CMBS/blob/main/cmbs/oplog_server.py)
and [cmbs/reducers.py](https://github.com/meadowlark-bradsher/CMBS/blob/main/cmbs/reducers.py)
for the full surface.

## EliminationStore SPI

A `typing.Protocol` for pluggable elimination persistence. Implementations
register sessions, persist tombstones idempotently, and answer survivor/recovery
queries. An in-memory implementation ships in the package.

```python
from cmbs import EliminationStore, InMemoryStore, EliminationProvenance

store: EliminationStore = InMemoryStore()
store.create_session("sid-1", frozenset({"H1", "H2", "H3"}))
result = store.eliminate(
    "sid-1",
    {"H1"},
    EliminationProvenance(source_id="adapter://demo", trigger="probe:P1"),
)
```

Key types: `EliminationStore`, `EliminationProvenance`, `EliminationResult`,
`RecoveredState`, `InMemoryStore`.

## LegacyReplayAdapter

A thin shim for audit continuity with pre-CMBS elimination logs.

```python
from cmbs import CMBSCore, LegacyReplayAdapter, LegacyEliminationEvent

core = CMBSCore(hypothesis_ids={"H1", "H2"})
adapter = LegacyReplayAdapter(core)

adapter.submit_elimination_event(
    LegacyEliminationEvent(
        probe_id="legacy:probe:001",
        observable_id="legacy:obs:alpha",
        eliminated_hypotheses={"H2"},
    )
)
```

## HypothesisProvider SPI

Plugin point for external packages to advertise hypothesis spaces to a
`BeliefServer`. Discovered via the `cmbs.hypotheses` entry point group with
`discover_providers()`.
