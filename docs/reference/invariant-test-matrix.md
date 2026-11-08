# Invariant Test Matrix

The kernel enforces a small set of named invariants. Each has dedicated test
coverage in `tests/test_session_invariants.py`, the 49-test suite carried
over from the original kernel and asserted against `Session`. This page
summarizes what is tested and where.

## Invariant summary

| ID      | Name                   | Description                                                                    | Classes                                                                    | Tests |
| ------- | ---------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------------------- | ----- |
| INV-2   | Stability window       | Termination requires N consecutive identical conclusions (when window > 0)     | `TestTerminationDiscipline`, `TestBoundaryNonSingletonTermination`, `TestBoundaryNonBinaryConclusion` | 10 |
| INV-3   | Probe non-repetition   | Duplicate `probe_id` submissions are rejected                                  | `TestINV3ProbeNonRepetition`                                               | 5     |
| INV-5a  | Entropy quantification | `entropy == log₂(\|survivors\|)`; queryable but never gating. Non-increasing under the default reducer, and under `ReinstatingMaskReducer` across any segment with no accepted `reinstate` | `TestINV5aEntropyQuantification` (monotonicity parametrized over both reducers), `TestEntropyObservation` | 11 |
| INV-6   | Non-trivial exit       | Obligation exit requires `min_eliminations` of progress within scope           | `TestINV6NonTrivialExit`, `TestObligationDiscipline`                       | 11    |

## Reinstatement invariants (`tests/test_reinstate.py`)

These hold under `ReinstatingMaskReducer` and are namespaced until they are
given numbered slots.

| ID      | Property                                                                                              | Class                            |
| ------- | ----------------------------------------------------------------------------------------------------- | -------------------------------- |
| INV-R1  | A `reinstate` targets exactly one in-force, accepted elimination envelope; each `(seq, h)` pair is reinstated at most once; a subset outside the asserted set is rejected | `TestReinstate`                  |
| INV-R2  | `h` survives iff no in-force pair names it; reinstating one of two killers does not revive `h`         | `TestReinstate`, property test   |
| INV-R3  | The log only grows; survivors grow only via `reinstate` and shrink only via elimination               | `TestReinstate`, property test   |
| INV-R4  | Reinstatement leaves `attrs` unchanged                                                                | `TestReinstate`                  |
| INV-O1  | `net` progress ≡ `\|eliminated_now − dead_at_open\|`; in-scope kill-then-reinstate nets 0; pre-open kills are inert both ways; never negative | `TestObligationSemantics`, property test |
| INV-O2  | A closed obligation record is unchanged by any later op                                               | `TestObligationSemantics`, property test |

The same file pins one v1 state hash so the new snapshot fields provably
leave `MaskMeetTombstoneReducer` hashes unchanged, and covers the retired
`retract` / `tombstone` ops, recovery through the version registry, and a
seeded random-sequence property test (`TestVocabulary`,
`TestHashingReplayRecovery`, `test_random_sequences_keep_the_invariants`;
54 tests).

## Budget, view, and weight invariants (`tests/test_view_and_budget.py`)

These also hold under `ReinstatingMaskReducer` and are namespaced until
given numbered slots.

| ID      | Property                                                                                              | Class                            |
| ------- | ----------------------------------------------------------------------------------------------------- | -------------------------------- |
| INV-B1  | With `max_reinstates=n`, the (n+1)-th `reinstate` is rejected with a reason and logged; state is unchanged; rejected reinstates never consume budget | `TestBudgetEnforcement`          |
| INV-B2  | With `max_reinstated_pairs=m`, a `reinstate` that would take `\|reinstated_pairs\|` past `m` is rejected whole; re-eliminating a reinstated hypothesis frees nothing | `TestBudgetEnforcement`          |
| INV-B3  | With `retractable` given, a `reinstate` the predicate refuses is rejected and logged; the predicate sees only what the snapshot recorded (`seq`, and `weight` when given), and only after the target is valid | `TestRetractablePredicate`       |
| INV-B4  | The budget acts in `check` only: a budgeted log replays to the same snapshot under the unbudgeted default; the version string is unchanged; recovery through the registry drops the budget and an explicit budgeted reducer keeps it | `TestBudgetConstruction`, `TestBudgetReplayAndRecovery` |
| INV-V1  | `view(k)` carries no survivor list; its size is bounded by `k` and the number of obligations, not by log length | `TestView`                       |
| INV-V2  | `view(k)` is a pure function of the snapshot and the last `k` envelopes; `Session.view` equals `snapshot().view(k, recent=operations()[-k:])`, before and after recovery | `TestView`                       |
| INV-W1  | `weight` is recorded iff given and the envelope asserted something; it never changes what is eliminated; `reason` stays in the payload only; v1 stores both and reads neither | `TestWeightAndReason`            |

The budget rows pin the mechanism-not-policy boundary from the
reinstatement side: the kernel bounds and refuses, the caller decides
(37 tests).

## Log integrity invariants (`tests/test_log_hash.py`)

These hold for every envelope `Session.append` writes, under either reducer.
`log_hash_n = sha256(log_hash_{n-1} || canonical(envelope_n))`, scheme
`log_hash_v1`; see [`compute_log_hash`](api.md#compute_log_hash).

| ID      | Property                                                                                              | Class                            |
| ------- | ----------------------------------------------------------------------------------------------------- | -------------------------------- |
| INV-H1  | Tamper evidence: editing any single field of envelope *n* (parametrized over all nine hashed fields, at three positions) changes `log_hash_n` and every later hash, and `Session.recover` raises `ValueError`; so does rewriting a hash alone, dropping an envelope, or a missing hash after the chain has started | `TestTamperEvidence`             |
| INV-H2  | Replay determinism: recomputing the chain from the persisted envelopes reproduces it exactly, `created_at` included (it is read from the record, not the clock); a recovered session reports the same head and continues the chain; a `provenance` edit moves `log_hash` but not `state_hash`, and `state_hash` stays on the snapshot and `AppendResult` | `TestReplayDeterminism`          |

`TestScheme` pins the scheme itself: genesis link, each link covering the
previous hash, canonical bytes as sorted-key compact UTF-8 JSON excluding the
hash field, and the stored scheme identifier. `TestLegacy` covers logs whose
envelopes carry `log_hash = None`: an all-legacy log loads with
`unverified_prefix` equal to its length, a legacy prefix followed by a
hashed tail verifies the tail, edits inside the prefix are (by design) not
detected, a session recovered from a legacy log starts its chain from
genesis, and a store written against the five-argument `create_session`
still works. `TestSerialization` round-trips `to_dict()`. One test records
the scheme's limit: a consistent rewrite of a whole suffix passes the chain
but cannot keep the head hash. 68 tests.

## Boundary properties

Beyond the numbered invariants, the suite asserts the architectural boundary
between mechanism and policy:

| Code            | Property                                | Class                                   | Tests |
| --------------- | --------------------------------------- | --------------------------------------- | ----- |
| B-OPAQUE        | Identifiers are opaque to the kernel    | `TestBoundaryOpaqueIdentifiers`         | 5     |
| B-NONSINGLETON  | Termination allowed at any cardinality  | `TestBoundaryNonSingletonTermination`   | 2     |
| B-NONBINARY     | Conclusions are not assumed binary      | `TestBoundaryNonBinaryConclusion`       | 2     |
| B-NONEXEC       | API is observation-only (no execution)  | `TestBoundaryNonExecutionSemantics`     | 3     |
| B-ADAPTER       | Lifecycle is adapter-driven             | `TestObligationDiscipline`, `TestTerminationDiscipline` | 11 |
| B-NONGATE       | Entropy is diagnostic, not gating       | `TestEntropyObservation`                | 4     |

## Test classes in `tests/test_session_invariants.py`

| Class                                  | Tests | Concern                                               |
| -------------------------------------- | ----- | ----------------------------------------------------- |
| `TestINV3ProbeNonRepetition`           | 5     | INV-3                                                 |
| `TestINV5aEntropyQuantification`       | 7     | INV-5a, including the conditional form under `ReinstatingMaskReducer` |
| `TestINV6NonTrivialExit`               | 6     | INV-6                                                 |
| `TestBoundaryOpaqueIdentifiers`        | 5     | B-OPAQUE                                              |
| `TestBoundaryNonSingletonTermination`  | 2     | B-NONSINGLETON, INV-2                                 |
| `TestBoundaryNonBinaryConclusion`      | 2     | B-NONBINARY, INV-2                                    |
| `TestBoundaryNonExecutionSemantics`    | 3     | B-NONEXEC                                             |
| `TestObligationDiscipline`             | 5     | INV-6, B-ADAPTER, robustness                          |
| `TestEntropyObservation`               | 4     | INV-5a, B-NONGATE                                     |
| `TestTerminationDiscipline`            | 6     | INV-2, B-ADAPTER                                      |
| `TestMigrationLegacyCompatibility`     | 4     | Legacy ID formats, recovery from a store, replay      |
| `TestMigrationIncrementalAdoption`     | 2     | Running alongside a legacy system; audit trail in the log |
| **Total**                              | **51** |                                                      |

## Substrate coverage in `tests/test_session_kernel.py`

The invariant suite is written against the facade. The kernel suite pins
down what the op-log substrate guarantees underneath it:

| Class                     | Tests | Guarantee                                                                            |
| ------------------------- | ----- | ------------------------------------------------------------------------------------ |
| `TestOpLog`               | 7     | Rejected ops enter the log with a reason; `seq` is contiguous; payloads are copied; provenance is stored opaque |
| `TestOpIdRetry`           | 2     | A repeated `op_id` returns the original envelope without appending, before and after recovery |
| `TestStateHash`           | 5     | Same log ⇒ same hash; hash covers session ID and reducer version; incremental state equals a full reduce |
| `TestReducerSemantics`    | 14    | `classify`; unknown ops are no-ops; `assert`/`refine`/`retract`; obligation re-entry rules; termination is idempotent and non-freezing; malformed ops are rejected, not raised |
| `TestConstruction`        | 8     | Input validation; ontology stored not interpreted; no execution-model terms on any public class |
| `TestStoreAndRecovery`    | 11    | `InMemoryOpLogStore` conformance; recovery reproduces the full snapshot and continues the same log; wrong reducer version is refused |
| `TestPositionDigest`      | 8     | `position_digest` equal across sessions with equal survivors; unchanged by zero-information ops; independent of order, path, universe, and session; names the meet of two positions |
| **Total**                 | **55** |                                                                                     |

## Cross-component coverage

The remaining tests exercise the layers above the kernel:

| File                        | Tests | Surface                                                  |
| --------------------------- | ----- | -------------------------------------------------------- |
| `test_examples.py`          | 9     | Both examples end to end; example log replays to the same snapshot |
| `test_kits.py`              | 7     | Kit loaders for both reference adapters                  |
| `test_legacy_adapter.py`    | 5     | `LegacyReplayAdapter`                                    |
| `test_spi.py`               | 4     | `HypothesisProvider` feeding a `Session`; `discover_providers` |
| `test_tutorials.py`         | 12    | Every tutorial offline; policy selection; a policy that insists on repeating is refused by the kernel |
| `test_reinstate.py`         | 54    | `ReinstatingMaskReducer`: INV-R1–R4, INV-O1–O2, the pinned v1 hash, the version registry, a random-sequence property test |
| `test_view_and_budget.py`   | 37    | The bounded view, the reinstatement budget, and `weight` / `reason`: INV-B1–B4, INV-V1–V2, INV-W1 |
| `test_log_hash.py`          | 68    | The `log_hash` chain: INV-H1–H2, the scheme definition, legacy logs and stores, `to_dict` round-trips |

Total across all files: **302 tests**.
