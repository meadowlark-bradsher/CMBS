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
| INV-5a  | Entropy quantification | `entropy == log₂(\|survivors\|)`; queryable but never gating                   | `TestINV5aEntropyQuantification`, `TestEntropyObservation`                 | 9     |
| INV-6   | Non-trivial exit       | Obligation exit requires `min_eliminations` within scope                       | `TestINV6NonTrivialExit`, `TestObligationDiscipline`                       | 11    |

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
| `TestINV5aEntropyQuantification`       | 5     | INV-5a                                                |
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
| **Total**                              | **49** |                                                      |

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

Total across all files: **141 tests**.
