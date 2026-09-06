# API Reference

The public surface is re-exported from the top-level `cmbs` package. This page
covers every exported symbol; the source files are the authoritative
reference.

```python
from cmbs import (
    Session, Snapshot, ObligationEntry, OntologyBundle,
    OperationSpec, OperationEnvelope, AppendResult,
    Reducer, MaskMeetTombstoneReducer, compute_state_hash, compute_position_digest,
    OpLogStore, InMemoryOpLogStore, RecoveredSession,
    ProbeResult, ObligationExitResult, TerminationResult,
    HypothesisProvider, discover_providers,
    LegacyReplayAdapter, LegacyEliminationEvent, submit_legacy_elimination,
)
```

## Session

The kernel. One instance is one investigation; state is
`reduce(initial_hypotheses, op_log)`.

```python
from cmbs import Session

session = Session(
    hypothesis_ids={"H1", "H2", "H3"},
    stability_window=0,   # 0 disables INV-2; positive N requires N consecutive identical conclusions
)
```

### Constructor

| Parameter          | Type                        | Default                       | Notes                                                        |
| ------------------ | --------------------------- | ----------------------------- | ------------------------------------------------------------ |
| `hypothesis_ids`   | `Iterable[str]`             | required                      | Initial universe. Any iterable of strings; duplicates collapse |
| `ontology`         | `OntologyBundle \| None`    | `None`                        | Stored for audit, never interpreted                          |
| `reducer`          | `Reducer \| None`           | `MaskMeetTombstoneReducer()`  | The fold from log to snapshot                                |
| `store`            | `OpLogStore \| None`        | `InMemoryOpLogStore()`        | Where envelopes are persisted                                |
| `stability_window` | `int`                       | `0`                           | INV-2 gate; must be `>= 0`                                   |
| `session_id`       | `str \| None`               | `None`                        | A UUID is generated if omitted                               |

### Imperative facade

| Method                                                                                   | Returns                | Notes                                                                           |
| ---------------------------------------------------------------------------------------- | ---------------------- | ------------------------------------------------------------------------------- |
| `submit_probe_result(probe_id, observable_id, eliminated, *, source_id="", provenance=None)` | `ProbeResult`     | Appends a `probe_result` op keyed by `probe_id`. A repeated `probe_id` is rejected and logged (INV-3) |
| `enter_obligation(obligation_id, min_eliminations=1, *, source_id="")`                   | `AppendResult`         | Adapter-initiated; rejected if `obligation_id` is already open                  |
| `request_obligation_exit(obligation_id, *, source_id="")`                                | `ObligationExitResult` | Permitted only after `min_eliminations` recorded within scope (INV-6)           |
| `declare_conclusion(conclusion_id, *, source_id="")`                                     | `AppendResult`         | Recorded for stability tracking                                                 |
| `request_termination(*, source_id="")`                                                   | `TerminationResult`    | Gated by the stability window when enabled (INV-2). Idempotent; does not freeze the session |

`source_id` and `provenance` are opaque provenance copied onto the envelope.

### Lower-level append

| Method                          | Returns        | Notes                                                                                     |
| ------------------------------- | -------------- | ----------------------------------------------------------------------------------------- |
| `append(spec: OperationSpec)`   | `AppendResult` | The reducer decides acceptance; the envelope enters the log either way. See [Operations](#operations) for the op types the shipped reducer understands |

Two dedupe rules apply, with different meanings:

- A repeated caller-supplied **`op_id`** is a transport retry: nothing is
  appended and the original envelope (with the state hash at its position)
  is returned.
- A repeated **`idempotency_key`** is a domain repeat: a new *rejected*
  envelope is appended so the attempt is auditable.

### Read access

| Property / method                    | Type                              | Description                                                        |
| ------------------------------------ | --------------------------------- | ------------------------------------------------------------------ |
| `session_id`                         | `str`                             |                                                                    |
| `survivors`                          | `frozenset[str]`                  | Currently surviving hypothesis IDs                                 |
| `entropy`                            | `float`                           | `log₂(\|survivors\|)`; `0.0` if `\|survivors\| <= 1`               |
| `consumed_probes`                    | `frozenset[str]`                  | Idempotency keys consumed by accepted ops (the facade's `probe_id`s) |
| `active_obligations`                 | `frozenset[str]`                  | Currently open obligation IDs                                      |
| `is_terminated`                      | `bool`                            | Whether `request_termination` has succeeded                        |
| `head_seq`                           | `int`                             | Seq of the last envelope (0 if empty)                              |
| `position_digest`                    | `str`                             | Session-independent identity of the survivor set; see [`compute_position_digest`](#compute_position_digest) |
| `initial_hypotheses`                 | `frozenset[str]`                  | The universe the session was created with                          |
| `ontology`, `stability_window`, `reducer` |                              | Construction parameters, read back                                 |
| `snapshot()`                         | `Snapshot`                        | Immutable view of the current state                                |
| `operations(from_seq=None, to_seq=None)` | `tuple[OperationEnvelope, ...]` | Envelopes in an inclusive, 1-indexed seq range                   |

### Recovery

```python
recovered = Session.recover(store, session_id, reducer=None)
```

Rebuilds a session by replaying its log from `store`. Raises `KeyError` if
the store does not know the session and `ValueError` if `reducer.version`
differs from the version that wrote the log.

## Snapshot

Frozen view of a session at a log position. Produced by the reducer;
returned by `Session.snapshot()`.

| Field                 | Type                             | Notes                                                    |
| --------------------- | -------------------------------- | -------------------------------------------------------- |
| `session_id`          | `str`                            |                                                          |
| `seq`                 | `int`                            | Log position this snapshot reflects (0 for a fresh session) |
| `state_hash`          | `str`                            | SHA-256; see [`compute_state_hash`](#compute_state_hash) |
| `survivors`           | `frozenset[str]`                 |                                                          |
| `eliminated`          | `frozenset[str]`                 |                                                          |
| `consumed_op_ids`     | `frozenset[str]`                 | Idempotency keys consumed so far                         |
| `obligations`         | `tuple[ObligationEntry, ...]`    | Open obligations in entry order                          |
| `conclusion_history`  | `tuple[str, ...]`                |                                                          |
| `terminated`          | `bool`                           |                                                          |
| `attrs`               | `dict[str, Any]`                 | Set by `assert` / `oracle_answer` ops; read by `refine`  |
| `stability_window`    | `int`                            | Carried so the reducer can gate INV-2 from the snapshot  |

Derived: `n_survivors`, `entropy`, `active_obligations`, `position_digest`,
`obligation(obligation_id) -> ObligationEntry | None`, and `to_dict()` for a
JSON-serializable form.

`ObligationEntry` has `obligation_id`, `min_eliminations`, and
`eliminations_in_scope`.

## Operations

```python
@dataclass(frozen=True)
class OperationSpec:        # what a caller submits
    op_type: str
    payload: dict[str, Any] = {}
    source_id: str = ""
    op_id: str | None = None
    idempotency_key: str | None = None

@dataclass(frozen=True)
class OperationEnvelope:    # what the kernel persists
    op_id: str
    seq: int
    op_type: str
    payload: dict[str, Any]
    source_id: str
    idempotency_key: str | None
    accepted: bool
    rejected_reason: str | None
    created_at: float

@dataclass(frozen=True)
class AppendResult:
    envelope: OperationEnvelope
    state_hash_after: str
    survivors_count_after: int
```

`OperationEnvelope.to_dict()` gives a JSON-serializable form.

### Op types understood by `MaskMeetTombstoneReducer`

| `op_type`              | Payload                                              | Effect when accepted                                                       |
| ---------------------- | ---------------------------------------------------- | -------------------------------------------------------------------------- |
| `probe_result`         | `observable_id`, `eliminate: [ids]`, optional `provenance` | Removes `eliminate ∩ survivors`. The facade sets `idempotency_key=probe_id` |
| `retract`, `tombstone` | `eliminate: [ids]`                                   | Same elimination, no facade                                                |
| `assert`, `oracle_answer` | `eliminate: [ids]`, `set: {attr: value}`          | Elimination plus writes into `Snapshot.attrs`                              |
| `refine`               | `if_attr`, `equals`, `eliminate: [ids]`              | Elimination only if `attrs[if_attr] == equals`                             |
| `enter_obligation`     | `obligation_id`, `min_eliminations`                  | Opens an obligation; rejected if already open or `min_eliminations < 0`    |
| `exit_obligation`      | `obligation_id`                                      | Closes it; rejected if not open or under threshold (INV-6)                 |
| `declare_conclusion`   | `conclusion_id`                                      | Appends to `conclusion_history`                                            |
| `request_termination`  | —                                                    | Sets `terminated`; rejected if the stability window is unmet (INV-2)       |
| anything else          | any                                                  | Accepted, no state change beyond advancing `seq`                           |

Every op with an `idempotency_key` is rejected if that key was already
consumed by an accepted op. Every newly eliminated hypothesis counts toward
every open obligation. Hypothesis IDs outside the session's universe are
ignored.

## Reducer

```python
@runtime_checkable
class Reducer(Protocol):
    version: str
    def initial(self, session_id, hypothesis_ids, *, stability_window=0) -> Snapshot: ...
    def check(self, snapshot, spec) -> tuple[bool, str | None]: ...
    def apply(self, snapshot, envelope) -> Snapshot: ...
    def reduce(self, initial_hypotheses, ops, *, session_id="", stability_window=0) -> Snapshot: ...
    def classify(self, op_type) -> str: ...
```

`check` runs once, at append time, and its verdict is persisted on the
envelope. `apply` folds one envelope: rejected envelopes only advance `seq`
and rehash; accepted ones mutate. `reduce` is `initial` folded through
`apply` over the whole log, rejected envelopes included. `classify` maps an
op type to one of `"elimination"`, `"obligation"`, `"conclusion"`,
`"termination"`, `"unknown"`.

`MaskMeetTombstoneReducer` is the shipped implementation, versioned
`"v1_mask_meet_tombstone"`. The version string is stored with the session and
checked on recovery.

### `compute_state_hash`

```python
compute_state_hash(snapshot: Snapshot, reducer_version: str) -> str
```

SHA-256 over the snapshot's canonical content (survivors, eliminated,
consumed keys, obligations, conclusion history, terminated flag, stability
window, attrs), the reducer version, the session ID, and `seq`. The hash does
not include `snapshot.state_hash` itself. Two snapshots hash equal iff they
describe the same belief at the same position of the same session under the
same reducer.

### `compute_position_digest`

```python
compute_position_digest(survivors: Iterable[str]) -> str
```

SHA-256 over the sorted survivor set and nothing else. Where `state_hash`
names a position in one session's log, this names a position in the belief
lattice: two sessions with the same survivors share a digest whatever their
IDs, log lengths, obligations, or conclusion history, and an op that
eliminates nothing leaves it unchanged. The universe is not included, so
pair it with `initial_hypotheses` when "this point in this lattice" matters.
Exposed as `Snapshot.position_digest` and `Session.position_digest`.

Typical uses: confirming two agents have converged without exchanging logs,
detecting a zero-information probe inside a loop, keying a policy cache or
value table on the frontier, and naming the meet of two positions
(`compute_position_digest(a.survivors & b.survivors)`).

## OpLogStore SPI

```python
@runtime_checkable
class OpLogStore(Protocol):
    def create_session(self, session_id, initial_hypotheses, ontology, stability_window, reducer_version) -> None: ...
    def append(self, session_id, envelope) -> None: ...
    def read_ops(self, session_id, from_seq=None, to_seq=None) -> tuple[OperationEnvelope, ...]: ...
    def head_seq(self, session_id) -> int: ...
    def recover(self, session_id) -> RecoveredSession: ...
```

`create_session` raises if the ID exists. `read_ops` bounds are inclusive and
1-indexed. `recover` returns a `RecoveredSession` with `session_id`,
`initial_hypotheses`, `ontology`, `stability_window`, `reducer_version`, and
`envelopes`.

`InMemoryOpLogStore` is the shipped implementation. It verifies that
envelopes arrive in contiguous seq order and raises `ValueError` otherwise;
unknown session IDs raise `KeyError`. Multiple sessions may share one store;
`session_ids()` lists them.

## Result types

```python
@dataclass(frozen=True)
class ProbeResult:
    accepted: bool
    error: str | None = None
    eliminated: frozenset[str] = frozenset()          # newly removed by this probe
    already_eliminated: frozenset[str] = frozenset()  # requested, but removed earlier

@dataclass(frozen=True)
class ObligationExitResult:
    permitted: bool
    error: str | None = None

@dataclass(frozen=True)
class TerminationResult:
    permitted: bool
    error: str | None = None
```

`error` carries the reducer's `rejected_reason` when a request is refused.

## OntologyBundle

```python
from cmbs import OntologyBundle

OntologyBundle(
    hypothesis_space_id="itbench",
    hypothesis_version="itb_min_4",
    causal_graph_ref="none",
    causal_graph_version="v0",
)
```

A versioned reference to the hypothesis space a session was built against.
Stored with the session and returned by recovery; never interpreted.

## HypothesisProvider SPI

Plugin point for external packages to advertise hypothesis spaces. A provider
exposes `id()`, `version()`, `hypothesis_ids()`, `probe_ids()`, and
`apply_probe(probe_id, response) -> Mapping[str, bool]` (an elimination
mask). Providers are discovered from the `cmbs.hypotheses` entry point group
with `discover_providers()`.

The kernel does not consume providers directly; the caller seeds a session
from `hypothesis_ids()` and turns each mask into a `submit_probe_result`:

```python
from cmbs import Session

session = Session(hypothesis_ids=provider.hypothesis_ids())
mask = provider.apply_probe("p1", response)
session.submit_probe_result(
    probe_id="p1",
    observable_id="p1:response",
    eliminated={hid for hid, gone in mask.items() if gone},
    source_id=f"provider://{provider.id()}@{provider.version()}",
)
```

## LegacyReplayAdapter

A thin shim for audit continuity with pre-CMBS elimination logs. It forwards
events to `submit_probe_result` with no validation or interpretation.

```python
from cmbs import Session, LegacyReplayAdapter, LegacyEliminationEvent

session = Session(hypothesis_ids={"H1", "H2"})
adapter = LegacyReplayAdapter(session, source_id="legacy://import")

adapter.submit_elimination_event(
    LegacyEliminationEvent(
        probe_id="legacy:probe:001",
        observable_id="legacy:obs:alpha",
        eliminated_hypotheses={"H2"},
    )
)
```

`submit_elimination_events(events)` submits a batch in order;
`submit_legacy_elimination(session, probe_id, observable_id, eliminated)` is
the one-call form.

## Reference adapters

`cmbs.adapters.twenty_questions` and `cmbs.adapters.itbench` are not
re-exported from the package root. Each ships `load_builtin_kit(name)`,
`load_kit(path)`, an adapter with `list_actions(snapshot)`,
`apply_action(action_id, snapshot)`, and `observe(ctx, outcome)`, and a
deterministic oracle. See
[examples/run_20q.py](https://github.com/meadowlark-bradsher/CMBS/blob/main/examples/run_20q.py)
and
[examples/run_itbench.py](https://github.com/meadowlark-bradsher/CMBS/blob/main/examples/run_itbench.py)
for the loop that connects them to a `Session`.
