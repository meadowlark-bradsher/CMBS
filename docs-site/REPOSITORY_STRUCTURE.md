# CMBS Repository Structure

This document describes the layout of the CMBS (Constraint Mask Belief System) repository.

## Overview

CMBS is a belief-state accounting system that tracks hypotheses, eliminations, entropy, and obligation discipline using opaque identifiers. The core is domain-agnostic—all semantics live in adapters.

```
cmbs/
├── cmbs/                    # Main package
│   ├── adapters/            # Domain-specific adapters
│   └── spi/                 # Service Provider Interface
├── docs-vault/              # Documentation vault (Obsidian-compatible)
├── tests/                   # Test suite
├── examples/                # Usage examples
└── archive/                 # Historical/deprecated code
```

---

## `cmbs/` — Main Package

The core belief-state accounting implementation.

### `cmbs/core.py`
**CMBS v0 Core** — The kernel of the system.

- `CMBSCore`: Main class tracking hypothesis survivors, consumed probes, obligations, and termination state
- `submit_probe_result()`: Submit an observation (the only way to eliminate hypotheses)
- `enter_obligation()` / `request_obligation_exit()`: Obligation lifecycle management
- `request_termination()`: Request session termination (gated by stability window)
- Enforces invariants: INV-3 (probe non-repetition), INV-5a (entropy), INV-6 (non-trivial exit)

### `cmbs/belief_server.py`
**Belief Server v1** — Session management layer wrapping the core.

- `BeliefServer`: Manages sessions, ontology bundles, and audit trails
- `BeliefSnapshot`: Immutable view of belief state at a point in time
- `AuditEntry`: Structured audit log entries with before/after hashes
- `OntologyBundle`: Versioned reference to hypothesis space and causal graph

### `cmbs/belief_state.py`
**BeliefState** — Lightweight belief state container.

- Thin wrapper providing a clean interface for belief state access
- Used by adapters to interact with belief state

### `cmbs/belief_api.py`
**Belief API** — HTTP/REST API definitions.

- Request/response models for remote belief server access
- JSON serialization for belief state operations

### `cmbs/__init__.py`
**Package exports** — Public API surface.

Exports: `CMBSCore`, `BeliefServer`, `BeliefSnapshot`, `BeliefState`, `HypothesisProvider`, `LegacyReplayAdapter`, etc.

---

## `cmbs/adapters/` — Domain-Specific Adapters

Adapters translate domain events into core operations. The core knows nothing about domains—adapters provide all semantics.

### `cmbs/adapters/types.py`
**Shared adapter types** — Common abstractions for all adapters.

- `Action`: Represents an action the agent can take
- `BeliefMessage` / `EliminateMessage`: Messages that update belief state
- `AdapterActionContext`: Context for action execution

### `cmbs/adapters/twenty_questions/`
**Twenty Questions adapter** — Example/test adapter for the classic game.

| File | Purpose |
|------|---------|
| `adapter.py` | `TwentyQAdapter`: Lists actions, applies actions, observes outcomes |
| `kit.py` | `TwentyQKit`: Game configuration (items, questions, elimination rules) |
| `oracle.py` | `TwentyQOracle`: Answers questions given the secret item |

### `cmbs/adapters/itbench/`
**ITBench adapter** — Adapter for IT operations benchmark scenarios.

| File | Purpose |
|------|---------|
| `adapter.py` | ITBench-specific action and observation logic |
| `kit.py` | ITBench configuration and probe definitions |
| `oracle.py` | Ground truth provider for ITBench scenarios |

### `cmbs/adapters/legacy/`
**Legacy replay adapter** — Thin shim for audit continuity with legacy logs.

| File | Purpose |
|------|---------|
| `replay.py` | `LegacyReplayAdapter`: Translates legacy elimination events to core calls |

---

## `cmbs/spi/` — Service Provider Interface

Extension points for pluggable hypothesis providers.

### `cmbs/spi/hypothesis_provider.py`
**HypothesisProvider** — Abstract base for hypothesis providers.

- Defines interface for providing hypothesis spaces to the belief server
- Allows external packages to register hypothesis providers

### `cmbs/spi/adapter.py`
**Provider discovery** — Entry point discovery for hypothesis providers.

- `discover_providers()`: Finds registered providers via `cmbs.hypotheses` entry points
- Enables plugin-style extension without modifying core code

---

## `docs-vault/` — Documentation

Obsidian-compatible documentation (uses `[[wikilinks]]` syntax).

| File | Purpose |
|------|---------|
| `ARCHITECTURE.md` | Core vs adapter boundary, invariants, out-of-scope items |
| `v0-test-specification.md` | Authoritative test specification for v0 invariants |
| `v0-implementation-summary.md` | Implementation notes and decisions |
| `v0-core-contract-validation.md` | Contract validation methodology |
| `BELIEF_SERVER_SPEC.md` | Belief server API specification |
| `ARCHIVE.md` | Notes on archived/deprecated code |
| `Home.md` | Documentation index |

---

## `tests/` — Test Suite

Pytest-based test suite organized by component.

| File | Purpose |
|------|---------|
| `test_v0_core.py` | **49 tests** — Authoritative invariant coverage (INV-3, INV-5a, INV-6, INV-2) |
| `test_invariants.py` | Additional invariant tests |
| `test_belief_server_spi_smoke.py` | Smoke tests for belief server + SPI integration |
| `test_spi_belief_state.py` | BeliefState abstraction tests |
| `test_legacy_adapter.py` | Legacy replay adapter tests |
| `conftest.py` | Pytest fixtures |

---

## `examples/` — Usage Examples

Runnable examples demonstrating CMBS usage.

| File | Purpose |
|------|---------|
| `run_20q.py` | Twenty Questions game using CMBS belief tracking |
| `run_itbench.py` | ITBench scenario execution with CMBS supervision |

---

## `archive/` — Historical Code

Deprecated code preserved for reference. **Do not import from archive.**

Contains:
- Original ITBench supervisor implementation (`cmbs/supervisor.py`, `cmbs/masks.py`, etc.)
- CCIL (Continuous CMBS Inference Layer) experimental code
- Document Search Repair Obligation (DSRO) design
- Early prototype scripts and experiments
- ITBench leaderboard reference materials

The archive exists for historical context and replay validation. All active development uses the `cmbs/` package.

---

## Root Files

| File | Purpose |
|------|---------|
| `README.md` | Project overview and quick start |
| `CLAUDE.md` | Instructions for Claude Code when working in this repo |
| `Dockerfile` | Container build for CMBS agent |
| `pytest.ini` | Pytest configuration |
| `requirements.txt` | Python dependencies |
| `.gitignore` | Git ignore patterns |

---

## Key Concepts

### Core vs Adapter Boundary

**Core responsibilities:**
- Track surviving hypotheses (opaque `Set[str]`)
- Record eliminations and audit history
- Enforce invariants (INV-3, INV-5a, INV-6)
- Optionally enforce conclusion stability (INV-2)

**Adapter responsibilities:**
- Provide hypothesis IDs and thresholds
- Translate domain events into core calls
- Interpret observables and domain semantics
- Decide when to declare conclusions or terminate

### Invariants

| ID | Name | Description |
|----|------|-------------|
| INV-2 | Stability | Termination requires N consecutive identical conclusions |
| INV-3 | Probe Non-Repetition | Duplicate probes are rejected |
| INV-5a | Entropy Quantification | Entropy = log₂(\|survivors\|) |
| INV-6 | Non-Trivial Exit | Obligation exit requires eliminations within scope |

### Hypothesis Spaces

CMBS v0 supports **discrete finite sets** only (`Set[str]`). It does not support:
- Continuous/Bayesian probability distributions
- Constraint graphs with arc consistency
- Diagnostic trees with feasible set intersection

These would require different update rules and a different core implementation.
