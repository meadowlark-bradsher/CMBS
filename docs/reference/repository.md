# Repository Layout

```
cmbs/                       # Source package
├── session.py              # Session — the kernel (facade + append + recovery)
├── reducer.py              # Reducer protocol, MaskMeetTombstoneReducer, compute_state_hash
├── snapshot.py             # Snapshot, ObligationEntry, OntologyBundle, result types
├── operations.py           # OperationSpec, OperationEnvelope, AppendResult
├── store.py                # OpLogStore protocol, InMemoryOpLogStore, RecoveredSession
├── spi/                    # Service Provider Interfaces
│   ├── hypothesis_provider.py  # HypothesisProvider protocol
│   └── adapter.py              # discover_providers() entry-point loader
└── adapters/               # Domain adapters
    ├── types.py                # Action, AdapterActionContext, BeliefAdapter, EliminateMessage
    ├── legacy/                 # LegacyReplayAdapter — audit continuity shim
    ├── twenty_questions/       # Example adapter for 20-questions
    │   └── kits/               # 20q_4.yaml, 20q_8.yaml
    └── itbench/                # ITBench scenarios
        └── kits/               # itb_min_4.yaml, itb_sre_6.yaml

tests/                      # Pytest suite (121 tests)
examples/                   # Runnable demos (run_20q.py, run_itbench.py)
design/                     # ADRs and the kernel comparison behind the current shape
docs/                       # This documentation tree (mkdocs source)
```

## Public surface

Everything re-exported from `cmbs/__init__.py` is part of the public API.
See the [API Reference](api.md) for every symbol.

## Test inventory

| File                               | Tests | Focus                                                                    |
| ---------------------------------- | ----- | ------------------------------------------------------------------------ |
| `tests/test_session_invariants.py` | 49    | Authoritative invariant coverage (INV-2, INV-3, INV-5a, INV-6) and boundary properties |
| `tests/test_session_kernel.py`     | 47    | Op log as audit trail, state hashing, `op_id` retries, reducer semantics beyond the facade, `OpLogStore` conformance, recovery |
| `tests/test_examples.py`           | 9     | Both examples end to end; replay of an example log to the same snapshot |
| `tests/test_kits.py`               | 7     | Kit loaders, including YAML `yes`/`no` key normalization                  |
| `tests/test_legacy_adapter.py`     | 5     | `LegacyReplayAdapter` shim                                               |
| `tests/test_spi.py`                | 4     | `HypothesisProvider` feeding a `Session`; `discover_providers`           |
| **Total**                          | **121** |                                                                        |

Run the full suite with `pytest -q` (well under a second).

## Build artifacts

| File                                  | Purpose                                                     |
| ------------------------------------- | ----------------------------------------------------------- |
| `pyproject.toml`                      | Packaging metadata (name, version, deps, build system) and `ruff` config |
| `requirements.txt`                    | Runtime dependencies (mirrors `pyproject.toml`)             |
| `mkdocs.yml`                          | Documentation site config (this tree)                       |
| `pytest.ini`                          | Pytest configuration                                        |
| `.github/workflows/tests.yml`         | CI: `ruff check .` and pytest on Python 3.10 / 3.11 / 3.12  |
| `.github/workflows/deploy-pages.yml`  | CI: build & publish this docs site to GitHub Pages          |

## Design records

| File                                | Content                                                     |
| ----------------------------------- | ----------------------------------------------------------- |
| `design/kernel-comparison.md`       | Side-by-side of the two earlier kernels that motivated unification |
| `design/adr-001-unify-kernels.md`   | Decision to unify them, with the implementation plan        |
| `design/adr-002-naming.md`          | Names for the unified surface                               |
