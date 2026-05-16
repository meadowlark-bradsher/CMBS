# Repository Layout

```
cmbs/                       # Source package
├── core.py                 # CMBSCore kernel — invariant enforcement
├── belief_state.py         # BeliefState container
├── belief_server.py        # BeliefServer v1 (session manager + audit log)
├── belief_api.py           # FastAPI HTTP surface
├── oplog_server.py         # OplogServer v2 (transcript-conditioned)
├── op_models.py            # OperationSpec, OperationEnvelope, BranchRecord, SessionRecord
├── reducers.py             # Reducer registry and projection utilities for v2
├── spi/                    # Service Provider Interfaces
│   ├── elimination_store.py    # EliminationStore protocol + provenance/result/recovery types
│   ├── hypothesis_provider.py  # HypothesisProvider protocol
│   └── adapter.py              # discover_providers() entry-point loader
├── stores/                 # SPI implementations shipped in the box
│   └── memory.py               # InMemoryStore
└── adapters/               # Domain adapters
    ├── types.py                # Shared adapter abstractions
    ├── legacy/                 # LegacyReplayAdapter — audit continuity shim
    ├── twenty_questions/       # Example adapter for 20-questions
    │   └── kits/               # 20q_4.yaml, 20q_8.yaml
    └── itbench/                # ITBench scenarios
        └── kits/               # itb_min_4.yaml, itb_sre_6.yaml

tests/                      # Pytest suite (77 tests)
examples/                   # Runnable demos (run_20q.py, run_itbench.py)
docs/                       # This documentation tree (mkdocs source)
```

## Public surface

Everything re-exported from `cmbs/__init__.py` is part of the public API.
See the [API Reference](api.md) for the high-traffic symbols.

## Test inventory

| File                                          | Tests | Focus                                                       |
| --------------------------------------------- | ----- | ----------------------------------------------------------- |
| `tests/test_v0_core.py`                       | 49    | Authoritative invariant coverage (INV-2, INV-3, INV-5a, INV-6) and boundary properties |
| `tests/test_oplog_server_v2.py`               | 8     | OplogServer v2 — branching, idempotency, merge conflicts    |
| `tests/test_elimination_store.py`             | 8     | InMemoryStore conformance against the EliminationStore SPI  |
| `tests/test_invariants.py`                    | 4     | Cross-cutting invariant tests                               |
| `tests/test_legacy_adapter.py`                | 3     | LegacyReplayAdapter shim                                    |
| `tests/test_spi_belief_state.py`              | 3     | BeliefState surface                                         |
| `tests/test_belief_server_spi_smoke.py`       | 1     | BeliefServer + SPI integration smoke                        |
| `tests/test_belief_server_store_integration.py` | 1   | BeliefServer + EliminationStore recovery path               |
| **Total**                                     | **77** |                                                            |

Run the full suite with `pytest -q` (~0.3s on modern hardware).

## Build artifacts

| File             | Purpose                                                     |
| ---------------- | ----------------------------------------------------------- |
| `pyproject.toml` | Packaging metadata (name, version, deps, build system)      |
| `requirements.txt` | Runtime dependencies (mirrors `pyproject.toml`)           |
| `mkdocs.yml`     | Documentation site config (this tree)                       |
| `pytest.ini`     | Pytest configuration                                        |
| `Dockerfile`     | Container build for serving `cmbs.belief_api:app`           |
| `.github/workflows/tests.yml` | CI: pytest on Python 3.10 / 3.11 / 3.12        |
| `.github/workflows/deploy-pages.yml` | CI: build & publish this docs site to GitHub Pages |
