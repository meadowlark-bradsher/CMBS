# Invariant Test Matrix

The kernel enforces a small set of named invariants. Each has dedicated test
coverage in `tests/test_v0_core.py`. This page summarizes what is tested and
where.

## Invariant summary

| ID      | Name                   | Description                                                                    | Tests |
| ------- | ---------------------- | ------------------------------------------------------------------------------ | ----- |
| INV-2   | Stability window       | Termination requires N consecutive identical conclusions (when window > 0)     | 10    |
| INV-3   | Probe non-repetition   | Duplicate `probe_id` submissions are rejected                                  | 5     |
| INV-5a  | Entropy quantification | `entropy == log₂(\|survivors\|)`; queryable but never gating                    | 14    |
| INV-6   | Non-trivial exit       | Obligation exit requires `min_eliminations` within scope                       | 10    |

## Boundary properties

Beyond the numbered invariants, the test suite asserts the architectural
boundary between mechanism and policy:

| Code            | Property                                | Tests |
| --------------- | --------------------------------------- | ----- |
| B-OPAQUE        | Identifiers are opaque to the kernel    | 6     |
| B-NONSINGLETON  | Termination allowed at any cardinality  | 2     |
| B-NONBINARY     | Conclusions are not assumed binary      | 2     |
| B-NONEXEC       | API is observation-only (no execution)  | 3     |
| B-ADAPTER       | Lifecycle is adapter-driven             | 4     |
| B-NONGATE       | Entropy is diagnostic, not gating       | 3     |

## Test classes in `tests/test_v0_core.py`

Tests are grouped into classes by concern:

| Class                              | Tests | Concern                                       |
| ---------------------------------- | ----- | --------------------------------------------- |
| `TestProbeNonRepetition`           | 5     | INV-3                                         |
| `TestEntropyQuantification`        | 5     | INV-5a                                        |
| `TestNonTrivialExit`               | 6     | INV-6                                         |
| `TestOpaqueIdentifiers`            | 5     | B-OPAQUE                                      |
| `TestNonSingletonTermination`      | 2     | B-NONSINGLETON                                |
| `TestNonBinaryConclusions`         | 2     | B-NONBINARY                                   |
| `TestNonExecutionSemantics`        | 3     | B-NONEXEC                                     |
| `TestObligationDiscipline`         | 5     | B-ADAPTER, robustness                         |
| `TestEntropyObservation`           | 4     | INV-5a, B-NONGATE                             |
| `TestTerminationDiscipline`        | 6     | INV-2                                         |
| `TestMigrationIncrementalAdoption` | 6     | Serialization, replay, audit trail            |

## Cross-component coverage

The remaining 28 tests in `tests/` exercise the layers above the kernel:

| File                                              | Tests | Surface                                    |
| ------------------------------------------------- | ----- | ------------------------------------------ |
| `test_oplog_server_v2.py`                         | 8     | `OplogServer`, reducers, branching         |
| `test_elimination_store.py`                       | 8     | `EliminationStore` SPI / `InMemoryStore`   |
| `test_invariants.py`                              | 4     | Cross-cutting invariant checks             |
| `test_legacy_adapter.py`                          | 3     | `LegacyReplayAdapter`                      |
| `test_spi_belief_state.py`                        | 3     | `BeliefState`                              |
| `test_belief_server_spi_smoke.py`                 | 1     | `BeliefServer` + SPI                       |
| `test_belief_server_store_integration.py`         | 1     | Recovery from `EliminationStore`           |

Total across all files: **77 tests**.
