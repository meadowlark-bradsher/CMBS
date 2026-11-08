# API Reference

The public surface is re-exported from the top-level `cmbs` package. This page
covers every exported symbol; the source files are the authoritative
reference.

```python
from cmbs import (
    Session, Snapshot, ObligationEntry, ClosedObligation, OntologyBundle,
    OBLIGATION_GROSS, OBLIGATION_NET,
    OperationSpec, OperationEnvelope, AppendResult,
    Reducer, MaskMeetTombstoneReducer, ReinstatingMaskReducer,
    register_reducer, reducer_for_version, registered_reducer_versions,
    compute_state_hash, compute_position_digest,
    OpLogStore, InMemoryOpLogStore, RecoveredSession,
    ProbeResult, ReinstateResult, ObligationExitResult, TerminationResult,
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
| `reducer`          | `Reducer \| None`           | `MaskMeetTombstoneReducer()`  | The fold from log to snapshot. Pass `ReinstatingMaskReducer()` to allow eliminations to be reinstated, optionally with a [reinstatement budget](#reinstatement-budget) |
| `store`            | `OpLogStore \| None`        | `InMemoryOpLogStore()`        | Where envelopes are persisted                                |
| `stability_window` | `int`                       | `0`                           | INV-2 gate; must be `>= 0`                                   |
| `session_id`       | `str \| None`               | `None`                        | A UUID is generated if omitted                               |

### Imperative facade

| Method                                                                                   | Returns                | Notes                                                                           |
| ---------------------------------------------------------------------------------------- | ---------------------- | ------------------------------------------------------------------------------- |
| `submit_probe_result(probe_id, observable_id, eliminated, *, source_id="", provenance=None, weight=None, reason=None)` | `ProbeResult`     | Appends a `probe_result` op keyed by `probe_id`. A repeated `probe_id` is rejected and logged (INV-3). `weight` (a number) and `reason` (a string) are copied into the payload when given; see [Op types](#op-types-understood-by-the-shipped-reducers) |
| `enter_obligation(obligation_id, min_eliminations=1, *, semantics=None, source_id="")`   | `AppendResult`         | Adapter-initiated; rejected if `obligation_id` is already open. `semantics` is `"gross"` or `"net"`; meaningful only under `ReinstatingMaskReducer`, where `"net"` is the default |
| `request_obligation_exit(obligation_id, *, source_id="")`                                | `ObligationExitResult` | Permitted only after `min_eliminations` of progress within scope (INV-6)        |
| `declare_conclusion(conclusion_id, *, source_id="")`                                     | `AppendResult`         | Recorded for stability tracking                                                 |
| `request_termination(*, source_id="")`                                                   | `TerminationResult`    | Gated by the stability window when enabled (INV-2). Idempotent; does not freeze the session |
| `reinstate(seq, hypotheses=None, *, reason=None, source_id="")`                          | `ReinstateResult`      | Voids the eliminations made by the envelope at `seq`, or only `hypotheses` of them. Requires `ReinstatingMaskReducer`; raises `NotImplementedError` otherwise |
| `reinstate_probe(probe_id, hypotheses=None, *, reason=None, source_id="")`               | `ReinstateResult`      | Same, naming the envelope by the `probe_id` it consumed. The probe ID stays consumed |

`source_id`, `provenance`, and `reason` are opaque provenance copied onto the
envelope. `weight` is opaque too, with one exception: `ReinstatingMaskReducer`
records it on the snapshot so a reinstatement budget's `retractable`
predicate can read it. The kernel itself never compares, sums, or thresholds
a weight.

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
| `closed_obligations`                 | `tuple[ClosedObligation, ...]`    | Frozen records of successful exits; empty under `MaskMeetTombstoneReducer` |
| `obligation_progress(obligation_id)` | `int \| None`                     | Progress of an open obligation under its declared semantics        |
| `is_terminated`                      | `bool`                            | Whether `request_termination` has succeeded                        |
| `head_seq`                           | `int`                             | Seq of the last envelope (0 if empty)                              |
| `position_digest`                    | `str`                             | Session-independent identity of the survivor set; see [`compute_position_digest`](#compute_position_digest) |
| `initial_hypotheses`                 | `frozenset[str]`                  | The universe the session was created with                          |
| `ontology`, `stability_window`, `reducer` |                              | Construction parameters, read back                                 |
| `snapshot()`                         | `Snapshot`                        | Immutable view of the current state                                |
| `view(k=5)`                          | `dict[str, Any]`                  | Bounded, JSON-serializable summary for a model-facing caller; see [`Snapshot.view`](#snapshotview) |
| `operations(from_seq=None, to_seq=None)` | `tuple[OperationEnvelope, ...]` | Envelopes in an inclusive, 1-indexed seq range                   |

### Recovery

```python
recovered = Session.recover(store, session_id, reducer=None)
```

Rebuilds a session by replaying its log from `store`. With `reducer=None`
the reducer registered for the stored version is used (see
[`reducer_for_version`](#reducer)). Raises `KeyError` if the store does not
know the session, and `ValueError` if no reducer is registered for the
stored version or an explicit `reducer.version` differs from it.

The registry returns a reducer in its default configuration. A
[reinstatement budget](#reinstatement-budget) is a constructor parameter,
not part of the version string and not stored with the session, so a
session recovered with `reducer=None` has **no** budget even if the original
had one. The log replays to the same snapshot either way, because the budget
only decides acceptance and the verdicts are already on the envelopes. To
keep enforcing a budget after recovery, pass the budgeted reducer:

```python
recovered = Session.recover(store, session_id, reducer=ReinstatingMaskReducer(max_reinstates=3))
```

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
| `asserted_pairs`      | `frozenset[tuple[int, str]]`     | Every `(seq, hypothesis)` an accepted elimination asserted dead. Populated only by `ReinstatingMaskReducer` |
| `reinstated_pairs`    | `frozenset[tuple[int, str]]`     | The subset of `asserted_pairs` voided by `reinstate`     |
| `key_seqs`            | `dict[str, int]`                 | Idempotency key → seq of the accepted envelope that consumed it |
| `closed_obligations`  | `tuple[ClosedObligation, ...]`   | Frozen records of successful exits                       |
| `weights`             | `dict[int, float]`               | Seq of an accepted elimination → the `weight` its payload carried. An entry exists only when a weight was given and the envelope asserted at least one hypothesis. Read by a budget's `retractable` predicate, never by the kernel |
| `reinstate_count`     | `int`                            | Accepted `reinstate` envelopes so far; what `max_reinstates` is checked against |

Derived: `n_survivors`, `entropy`, `active_obligations`, `position_digest`,
`in_force_pairs`, `obligation(obligation_id) -> ObligationEntry | None`,
`obligation_progress(obligation_id) -> int | None`, `killers(hypothesis_id)
-> frozenset[int]` (seqs of in-force envelopes holding it dead),
`asserted_dead(seq) -> frozenset[str]`, `to_dict()` for a JSON-serializable
form of everything, and `view(k, recent)` for a bounded one.

### `Snapshot.view`

```python
snapshot.view(k: int = 5, recent: Sequence[OperationEnvelope] = ()) -> dict[str, Any]
session.view(k: int = 5) -> dict[str, Any]
```

A JSON-serializable summary whose size does not grow with the log, meant to
be handed to a model or an operator in place of `to_dict()`. It never
includes the survivor list, the eliminated list, or the pair sets. Keys:

| Key                  | Value                                                                 |
| -------------------- | --------------------------------------------------------------------- |
| `session_id`, `seq`, `state_hash`, `position_digest` | As on the snapshot                                   |
| `n_survivors`, `entropy`, `terminated` | As on the snapshot                                                   |
| `obligations`        | One entry per open obligation: `obligation_id`, `semantics`, `min_eliminations`, `progress` under the declared semantics |
| `closed_obligations` | The `ClosedObligation` records, as in `to_dict()`                     |
| `n_in_force_pairs`, `n_reinstated_pairs`, `reinstate_count` | Counts; all `0` under `MaskMeetTombstoneReducer` |
| `recent`             | The last `k` envelopes, each reduced to `seq`, `op_type`, `accepted`, `rejected_reason` |

`Snapshot.view` is a pure function of the snapshot and `recent`; the snapshot
holds no envelopes, so the caller supplies them, and only the last `k` of
whatever is passed are used. `Session.view(k)` reads the last `k` envelopes
from the store and is equal to `snapshot().view(k, recent=operations()[-k:])`.
`k=0` yields an empty `recent`; a negative `k` raises `ValueError`.

`ObligationEntry` has `obligation_id`, `min_eliminations`,
`eliminations_in_scope`, and, under `ReinstatingMaskReducer`, `open_seq`,
`semantics` (`"gross"` or `"net"`), and `dead_at_open`. Its
`progress(eliminated)` is `eliminations_in_scope` for `gross` and
`|eliminated − dead_at_open|` for `net`.

`ClosedObligation` has `obligation_id`, `open_seq`, `exit_seq`, `semantics`,
`min_eliminations`, and `progress_at_exit`. It is written once, on an
accepted `exit_obligation`, and never changed.

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

### Op types understood by the shipped reducers

| `op_type`              | Payload                                              | Effect when accepted                                                       |
| ---------------------- | ---------------------------------------------------- | -------------------------------------------------------------------------- |
| `probe_result`         | `observable_id`, `eliminate: [ids]`, optional `provenance`, `weight`, `reason` | Removes `eliminate ∩ survivors`. The facade sets `idempotency_key=probe_id`. `weight` (a real number) and `reason` (a string) are optional on every elimination op; under v2 a malformed one is rejected with a reason, and an accepted `weight` is recorded as `Snapshot.weights[seq]`. Neither changes what is eliminated |
| `retract`, `tombstone` | `eliminate: [ids]`                                   | **v1 only:** same elimination, no facade. Retired under `ReinstatingMaskReducer`, which rejects them with a reason |
| `assert`, `oracle_answer` | `eliminate: [ids]`, `set: {attr: value}`          | Elimination plus writes into `Snapshot.attrs`                              |
| `refine`               | `if_attr`, `equals`, `eliminate: [ids]`              | Elimination only if `attrs[if_attr] == equals`                             |
| `reinstate`            | `seq` or `probe_id`, optional `hypotheses: [ids]`, optional `reason` | **v2 only:** voids the in-force eliminations of that one accepted elimination envelope, or only the named subset. Rejected if the target is not an accepted elimination, is out of range, is already reinstated, the subset names a hypothesis it never asserted, or the reducer's [reinstatement budget](#reinstatement-budget) refuses it |
| `enter_obligation`     | `obligation_id`, `min_eliminations`, optional `semantics` | Opens an obligation; rejected if already open or `min_eliminations < 0`. `semantics` (`"gross"` or `"net"`, default `"net"`) is read by v2 only |
| `exit_obligation`      | `obligation_id`                                      | Closes it; rejected if not open or under threshold (INV-6)                 |
| `declare_conclusion`   | `conclusion_id`                                      | Appends to `conclusion_history`                                            |
| `request_termination`  | —                                                    | Sets `terminated`; rejected if the stability window is unmet (INV-2)       |
| anything else          | any                                                  | Accepted, no state change beyond advancing `seq`                           |

Every op with an `idempotency_key` is rejected if that key was already
consumed by an accepted op. Every newly eliminated hypothesis counts toward
every open obligation. Hypothesis IDs outside the session's universe are
ignored.

Under `ReinstatingMaskReducer`, an elimination envelope also records every
hypothesis it asserted dead, whether or not that hypothesis was still a
survivor, and a hypothesis is eliminated iff at least one such record is
still in force. Reinstating one of two envelopes that both killed `H` leaves
`H` dead. Reinstatement never touches `attrs` and never un-consumes an
idempotency key.

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
op type to one of `"elimination"`, `"reinstatement"`, `"obligation"`,
`"conclusion"`, `"termination"`, `"unknown"`.

Two reducers ship. The version string is stored with the session and checked
on recovery.

- **`MaskMeetTombstoneReducer`**, `"v1_mask_meet_tombstone"`, the default.
  Monotone set elimination: survivors only shrink.
- **`ReinstatingMaskReducer`**, `"v2_mask_reinstate"`. Same vocabulary and
  gates, plus the `reinstate` op and per-obligation `gross` / `net`
  semantics. The monotone object becomes the pair of record sets
  `(asserted_pairs, reinstated_pairs)`, which only grow; the survivor set is
  a derived view that may grow or shrink. Entropy is non-increasing across
  any log segment with no accepted `reinstate`.

Reducers are looked up by version through a registry:
`register_reducer(cls)` (a class decorator) adds one,
`reducer_for_version(version)` instantiates it with default configuration
or raises `ValueError`, and `registered_reducer_versions()` lists the known
versions. `Session.recover` uses the registry when no reducer is passed.

### Reinstatement budget

```python
ReinstatingMaskReducer(
    *,
    max_reinstates: int | None = None,          # cap on accepted reinstate ops
    max_reinstated_pairs: int | None = None,    # cap on |reinstated_pairs|
    retractable: Callable[[Mapping[str, Any]], bool] | None = None,
)
```

All three default to unlimited. When set, `check` applies them to a
`reinstate` that is otherwise acceptable, in this order:

1. `max_reinstates`: rejected if `snapshot.reinstate_count` has reached the
   cap. Rejected reinstates never count.
2. `max_reinstated_pairs`: rejected if voiding the requested pairs would take
   `|reinstated_pairs|` past the cap. The op is rejected whole; no partial
   voiding. The record set is monotone, so a pair stays counted even if its
   hypothesis is later eliminated again.
3. `retractable`: called with what the snapshot recorded about the target
   elimination envelope, a mapping holding `"seq"` and, when the envelope
   carried one, `"weight"`. Returning `False` rejects the op. The predicate
   must be total: an exception propagates out of `append` and nothing is
   logged.

A refused `reinstate` is logged as a rejected envelope with a reason naming
the limit, exactly like any other rejection, and leaves the snapshot
unchanged apart from `seq`.

The budget is **mechanism, not policy**: the reducer bounds how much
reinstatement a log may contain, and refuses attempts past the bound, but it
never decides to reinstate anything. Deciding when a prior elimination was
wrong remains the caller's, and the kernel has no trigger for it. The
limits act only in `check`; `apply` is the same fold whatever they are, so a
log written under a budgeted reducer replays to the same snapshot under the
unbudgeted default and the `version` string is unchanged. Consequently the
budget is not stored with the session: `reducer_for_version` and
`Session.recover(..., reducer=None)` return the unbudgeted reducer, and a
caller who wants the limits kept passes the budgeted instance to `recover`.
`reducer.budgeted` reports whether any limit is set.

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

The fields only `ReinstatingMaskReducer` populates (`asserted_pairs`,
`reinstated_pairs`, `key_seqs`, `closed_obligations`, `weights`,
`reinstate_count`, and an obligation's `open_seq` / `semantics` /
`dead_at_open`) enter the hashed content only when non-empty, so hashes
computed under `MaskMeetTombstoneReducer` are byte-identical to those of
earlier releases.

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
class ReinstateResult:
    accepted: bool
    error: str | None = None
    voided: frozenset[str] = frozenset()   # eliminations by the target envelope that were voided
    revived: frozenset[str] = frozenset()  # the subset that returned to the survivor set

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
