# Changelog

All notable changes to CMBS are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once it reaches 1.0.0.

## [Unreleased]

The v0 and v2 kernels are unified into a single `Session` kernel per
[ADR-001](design/adr-001-unify-kernels.md) and
[ADR-002](design/adr-002-naming.md). No published consumers existed, so
the old surface is removed outright rather than deprecated.

### Added
- `Session` — the unified kernel. One instance is one investigation;
  state is `reduce(initial_hypotheses, op_log)`. Imperative facade
  (`submit_probe_result`, `enter_obligation`, `request_obligation_exit`,
  `declare_conclusion`, `request_termination`) plus a lower-level
  `append(OperationSpec)`; `snapshot()`, `operations()`, and
  `Session.recover(store, session_id)`.
- `Reducer` protocol and the shipped `MaskMeetTombstoneReducer`
  (`"v1_mask_meet_tombstone"`), which enforces INV-2, INV-3, and INV-6 at
  append time and records rejected ops in the log with a reason.
- `OpLogStore` persistence SPI with `InMemoryOpLogStore`; recovery
  returns a `RecoveredSession` and refuses to replay under a different
  reducer version.
- `Snapshot`, `OperationSpec`, `OperationEnvelope`, `AppendResult`,
  `compute_state_hash`.
- `compute_position_digest` and `Snapshot.position_digest` /
  `Session.position_digest`: a session-independent identity for the
  survivor set, for convergence checks, zero-information-probe detection,
  and policy caching across runs.
- `load_builtin_kit(name)` in both reference adapters
  (`cmbs.adapters.twenty_questions`, `cmbs.adapters.itbench`) — loads
  kit YAMLs via `importlib.resources` so examples and downstream users
  work after `pip install`, not just from a repo checkout.
- `ruff` linter configured in `pyproject.toml`; enforced in CI.
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, GitHub issue
  and pull-request templates.
- `tutorials/`: six runnable scripts (kernel basics, LLM Twenty Questions,
  LLM incident triage, two-agent convergence, audit and replay, a
  file-backed store). The LLM ones drive the investigation with Claude
  via the `anthropic` SDK when a key is visible and fall back to a
  scripted policy otherwise. Installed with `pip install 'cmbs[tutorials]'`.
- Tests: `test_session_invariants.py` (the 49 v0 invariant tests ported
  to `Session`), `test_session_kernel.py` (op log, hashing, retries,
  store SPI, recovery), `test_spi.py`, `test_examples.py`.

### Changed
- `LegacyReplayAdapter` and `submit_legacy_elimination` now take a
  `Session` instead of a `CMBSCore`, and accept an optional `source_id`.
- `BeliefAdapter` / `AdapterActionContext` are typed against `Snapshot`.
- Examples drive a `Session` directly and use `load_builtin_kit`
  instead of hardcoded relative paths.
- Runtime dependencies reduced to `pyyaml`. CMBS is library-only at v1.
- A repeated `probe_id` is logged as a rejected envelope rather than
  silently ignored, so the attempt is auditable.
- `docs/` rewritten against the unified surface: architecture (state as
  the reduction of a log), use cases, full API reference, repository
  layout, and the invariant test matrix.

### Removed
- `CMBSCore`, `BeliefState`, `BeliefServer`, `BeliefSnapshot`,
  `AuditEntry`, `EliminationEvent` (v0) — replaced by `Session`,
  `Snapshot`, and the op log.
- `OplogServer`, `OplogServerError`, `OpAppendResult`, `BranchRecord`,
  `SessionRecord`, and the reducer registry (v2) — replaced by `Session`,
  `AppendResult`, and `MaskMeetTombstoneReducer`. Branching, merge, and
  commutativity analysis are not carried over; the op log makes them
  reintroducible as a layer on top when a use case needs them.
- `EliminationStore` SPI, `EliminationProvenance`, `EliminationResult`,
  `RecoveredState`, `InMemoryStore` — replaced by `OpLogStore`,
  `InMemoryOpLogStore`, and `RecoveredSession`.
- FastAPI HTTP surface (`cmbs.belief_api`), `Dockerfile`,
  `.dockerignore`, and the `fastapi`, `pydantic`, `uvicorn` dependencies.
  Client-server access can return as separate work on top of the kernel.

## [0.1.0] — 2026-05-16

Initial public release.

### Added
- `CMBSCore` kernel — opaque-ID hypothesis tracking with monotone
  elimination, entropy quantification, obligation discipline, and
  optional stability-window termination.
- `BeliefServer` — multi-session manager with `OntologyBundle`
  references, hash-chained `AuditEntry` records, and a
  `HypothesisProvider` SPI for plugin-style hypothesis spaces.
- `OplogServer` (v2) — transcript-conditioned session model where
  `state = reduce(reducer_version, op_log_prefix(branch, seq))`, with
  branching, idempotency keys, and `409 NON_COMMUTATIVE_CONFLICT` on
  non-commutative merges.
- `EliminationStore` SPI with an in-memory implementation
  (`InMemoryStore`) — recovery path returns `RecoveredState` for crash
  recovery.
- Reference adapters: `LegacyReplayAdapter`, `TwentyQAdapter`,
  `ITBenchAdapter`, each with kit YAMLs shipped as package data.
- Public documentation tree under `docs/`: home, use cases,
  architecture, API reference, repository layout, invariant test matrix.
- Apache 2.0 license and `pyproject.toml` packaging metadata.
- CI workflow running `pytest` on Python 3.10 / 3.11 / 3.12.
- 77 tests covering kernel invariants, server lifecycle, SPI conformance,
  and the v2 oplog model.

[Unreleased]: https://github.com/meadowlark-bradsher/CMBS/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/meadowlark-bradsher/CMBS/releases/tag/v0.1.0
