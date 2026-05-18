# Changelog

All notable changes to CMBS are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once it reaches 1.0.0.

## [Unreleased]

### Added
- `load_builtin_kit(name)` in both reference adapters
  (`cmbs.adapters.twenty_questions`, `cmbs.adapters.itbench`) — loads
  kit YAMLs via `importlib.resources` so examples and downstream users
  work after `pip install`, not just from a repo checkout.
- `ruff` linter configured in `pyproject.toml`; enforced in CI.
- `.dockerignore`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `CHANGELOG.md`, GitHub issue and pull-request templates.

### Changed
- Examples now use `load_builtin_kit` instead of hardcoded relative paths.

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
