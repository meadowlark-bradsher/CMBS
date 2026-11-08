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
- `ReinstatingMaskReducer` (`"v2_mask_reinstate"`), an opt-in sibling of
  the default reducer under which an elimination can be voided by a
  logged `reinstate` op while the log and the record set stay monotone.
  Every elimination records each hypothesis it asserted dead as a
  `(seq, hypothesis)` pair; a hypothesis survives iff no pair naming it is
  in force, so reinstating one of two killers does not revive it.
  `Session.reinstate(seq, hypotheses=None)` and
  `Session.reinstate_probe(probe_id, hypotheses=None)` drive it and
  return a `ReinstateResult`. Reinstatement never touches `attrs` and
  never un-consumes a probe ID. The retired `retract` / `tombstone` ops
  are rejected with a reason under this reducer; other unknown op types
  remain silent no-ops.
- Obligation counting semantics, declared per obligation via
  `enter_obligation(..., semantics="gross" | "net")` and read by
  `ReinstatingMaskReducer` only. `gross` is the running in-scope count
  and ignores reinstatement; `net` (the default there) is
  `|eliminated_now − eliminated_at_open|`, so an in-scope
  eliminate-then-reinstate earns nothing. Successful exits leave a frozen
  `ClosedObligation` record on the snapshot (`Session.closed_obligations`),
  and `Session.obligation_progress(id)` reports progress under the declared
  semantics.
- New `Snapshot` fields `asserted_pairs`, `reinstated_pairs`, `key_seqs`,
  `closed_obligations`, plus `killers(h)`, `asserted_dead(seq)`,
  `in_force_pairs`, and `obligation_progress(id)`. `ObligationEntry` gains
  `open_seq`, `semantics`, `dead_at_open`, and `progress(eliminated)`. All
  default to empty and enter the state hash only when non-empty, so hashes
  under the default reducer are unchanged (pinned by test).
- A reducer version registry: `register_reducer`, `reducer_for_version`,
  `registered_reducer_versions`. `Session.recover` picks the reducer from
  the stored version when none is passed, and raises `ValueError` for an
  unregistered version.
- `Snapshot.view(k=5, recent=())` and `Session.view(k=5)`: a
  JSON-serializable, model-facing summary whose size does not grow with
  the log. Survivor count, entropy, position digest, open obligations with
  declared semantics and current progress, the closed-obligation records,
  the numbers of in-force and reinstated pairs, and the last `k` envelopes
  as `seq` / `op_type` / `accepted` / `rejected_reason`. Never the survivor
  list. A pure function of the snapshot plus those `k` envelopes, which
  `Session.view` reads from the store.
- A reinstatement budget on `ReinstatingMaskReducer`, set by constructor:
  `max_reinstates` (accepted `reinstate` ops over the session),
  `max_reinstated_pairs` (voided pairs), and a `retractable(recorded)`
  predicate called with the target elimination's `seq` and recorded
  `weight`. A `reinstate` past a cap or refused by the predicate is
  rejected with a reason naming the limit and logged like any other
  rejection. The reducer enforces the bound; it never decides to
  reinstate. The budget acts in `check` only, so the `version` string is
  unchanged and a budgeted log replays identically under the default
  reducer. It is not stored with the session: `reducer_for_version` and
  `Session.recover(..., reducer=None)` yield the unbudgeted reducer, and a
  budgeted one is passed to `recover` explicitly. `reducer.budgeted`
  reports whether any limit is set.
- Optional `weight` (a real number) and `reason` (a string) on elimination
  payloads, accepted as keyword arguments by `submit_probe_result` and
  copied into the payload only when given. The kernel never interprets
  either. Under `ReinstatingMaskReducer` a malformed one is rejected with a
  reason, and an accepted `weight` is recorded as `Snapshot.weights[seq]`
  (only when the envelope asserted at least one hypothesis) so the budget
  predicate can read it; `reason` stays in the envelope payload.
  `Snapshot.reinstate_count` counts accepted `reinstate` envelopes. Both
  new fields default to empty and enter the state hash only when
  populated, so v1 hashes are still byte-identical.
- `tests/test_view_and_budget.py`: the namespaced invariants INV-B1–B4,
  INV-V1–V2, and INV-W1.
- `tests/test_reinstate.py`: the namespaced invariants INV-R1–R4 and
  INV-O1–O2, a pinned v1 hash, recovery through the registry, and a
  seeded random-sequence property test. INV-5a's monotonicity test now
  runs under both reducers, with a new test for its conditional form.
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
- A docs walkthrough page per tutorial under *Tutorials*, with the real
  output, what to notice, and a link to the source.
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
