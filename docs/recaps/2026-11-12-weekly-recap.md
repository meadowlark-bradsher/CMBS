# Weekly recap: 6 to 12 November 2026

**The week CMBS shipped 0.2.0.** The whole v0.2.0 reinstatement spec, agreed
as a build-ready draft on the morning of Saturday 8 November, was implemented,
reviewed, merged and released the same day in five pull requests. The test
suite more than doubled, every invariant the spec named is now pinned by a
test, and the default reducer's state hashes are byte-identical to 0.1.0.

## Headline outcomes

- **CMBS 0.2.0 is released.** Tag `v0.2.0` sits on the merge of
  [PR #15](https://github.com/meadowlark-bradsher/CMBS/pull/15) and the GitHub
  release was published on 2026-11-08. The package version and the dated
  changelog section match.
- **Eliminations are now retractable without giving up the monotone log.**
  `ReinstatingMaskReducer` makes the record set the lattice and the survivor
  set a derived view, so a `reinstate` op can revive a hypothesis while the
  log and the record set only grow.
- **The log is tamper-evident.** Every envelope carries a chained
  `log_hash`, recomputed and verified on recovery. A single edited field in a
  persisted log makes `Session.recover` raise at that seq.
- **The kernel bounds reinstatement but never decides it.** A reinstatement
  budget is enforced in `check()` only, so the mechanism/policy line the
  architecture promises holds and the version string did not change.
- **Models get a bounded view.** `Session.view(k)` is O(1) in log length and
  never exposes the survivor list.
- **Backward compatibility held.** The v1 reducer's state hash on a fixed log
  is pinned by test and unchanged. Legacy logs with no `log_hash` still load.
  Stores written against the old five-argument `create_session` keep working.
- **Quality gates stayed green.** Suite at 302 passed, `ruff check` clean,
  `mkdocs build --strict` clean, and the docs site deployed successfully on
  every merge to `main`.

## By the numbers

| PR | Merged (UTC) | Added | Removed | Files | New tests |
|---|---|---|---|---|---|
| [#12](https://github.com/meadowlark-bradsher/CMBS/pull/12) Phase 1: `ReinstatingMaskReducer` | 2026-11-08 17:38 | 1,424 | 58 | 14 | 54 |
| [#13](https://github.com/meadowlark-bradsher/CMBS/pull/13) Phase 3: view, budget, weight/reason | 2026-11-08 17:48 | 953 | 32 | 8 | 37 |
| [#14](https://github.com/meadowlark-bradsher/CMBS/pull/14) Phase 2: chained `log_hash` | 2026-11-08 17:51 | 864 | 21 | 10 | 68 |
| [#15](https://github.com/meadowlark-bradsher/CMBS/pull/15) Release 0.2.0 | 2026-11-08 17:57 | 7 | 2 | 2 | 0 |
| [#16](https://github.com/meadowlark-bradsher/CMBS/pull/16) README leads with the live site | 2026-11-08 18:27 | 4 | 3 | 1 | 0 |

Test suite over the week: 141 before Phase 1, 197 after it, 234 after Phase 3,
302 after Phase 2. Test counts are as collected by pytest, so parametrized
cases are counted individually.

## The idea that made it work

Before this week, survivors formed a meet-semilattice and could only descend.
Making an elimination retractable looked like it meant breaking monotonicity.
The resolution: change what is monotone. Every accepted elimination records a
`(seq, hypothesis)` pair for each hypothesis it asserted dead, whether or not
that hypothesis was still a survivor. A `reinstate` records the pairs it voids.
Both record sets only grow. A hypothesis is eliminated exactly when at least
one pair naming it is in force, so the survivor set is a view that can move
back up without any record ever being removed.

Two consequences fall out for free. Reinstating one of two killers does not
revive a hypothesis the other still holds. And entropy is non-increasing across
any log segment with no accepted `reinstate`, which is the conditional form of
INV-5a that the test matrix now carries.

## Phase 1: `ReinstatingMaskReducer` (PR #12)

- An opt-in sibling of the default reducer, version string
  `"v2_mask_reinstate"`. The default reducer is untouched.
- `reinstate` names one accepted elimination by `seq` or by the `probe_id` it
  consumed, optionally restricted to a subset of its asserted set. It is
  rejected and logged with a reason if the target is not an accepted
  elimination, is out of range, is already reinstated, or the subset names a
  hypothesis the envelope never asserted.
- Reinstatement touches lattice state only. It never changes `attrs` and never
  un-consumes a probe ID, so INV-3 still holds.
- Obligations declare counting semantics at entry. `gross` is the running
  in-scope count and ignores reinstatement, matching v1. `net`, the default
  under the new reducer, is the size of the symmetric difference between the
  dead set now and the dead set at open, so an in-scope eliminate-then-reinstate
  earns nothing. Successful exits leave a frozen `ClosedObligation` record.
- The retired `retract` and `tombstone` ops are rejected with a reason instead
  of silently passing. Other unknown op types stay silent no-ops, as
  documented.
- A version-to-reducer registry. `Session.recover` picks the reducer from the
  stored version when none is passed and raises on an unregistered one.
- Facade additions: `Session.reinstate`, `Session.reinstate_probe`, a
  `semantics` keyword on `enter_obligation`, `closed_obligations`,
  `obligation_progress`. Calling `reinstate` under a reducer without support
  raises `NotImplementedError` rather than appending a silently accepted no-op.
- New invariants INV-R1 to R4 and INV-O1 to O2, a 12-seed random-sequence
  property test, and the pinned v1 hash.

## Phase 3: bounded view, reinstatement budget, weight and reason (PR #13)

Merged before Phase 2, since it was independent of the hash work.

- `Snapshot.view(k, recent)` and `Session.view(k)` return a JSON-serializable
  summary: survivor count, entropy, position digest, open obligations with
  semantics and progress, closed-obligation records, pair counts, and the last
  `k` envelopes reduced to `seq`, `op_type`, `accepted`, `rejected_reason`.
  The survivor list is deliberately absent. The view is a pure function of the
  snapshot plus those `k` envelopes, and is identical before and after
  recovery.
- `ReinstatingMaskReducer(max_reinstates=, max_reinstated_pairs=,
  retractable=)` adds a budget. A `reinstate` past a cap or refused by the
  predicate is rejected with a reason naming the limit. Rejected reinstates
  never consume budget.
- The budget acts in `check` only, so `apply` is the same fold whatever the
  limits and a budgeted log replays identically under the unbudgeted default.
  That is why the version string did not change and why the budget is not
  stored with the session: recovery through the registry yields the unbudgeted
  reducer, and a caller who wants the limits kept passes the budgeted instance
  to `recover` explicitly.
- Optional `weight` and `reason` on elimination payloads, as keyword arguments
  to `submit_probe_result`, copied in only when given so existing envelopes
  are byte-identical. The kernel never interprets either. Under v2 the weight
  is recorded as `Snapshot.weights[seq]` so the budget predicate can read it.
- "What the kernel does not do" in the architecture page now names the
  reinstatement trigger explicitly: the kernel can bound reinstatement and
  refuse attempts past the bound, but never issues one.
- New invariants INV-B1 to B4, INV-V1 to V2, INV-W1.

## Phase 2: chained per-envelope `log_hash` (PR #14)

- Scheme `log_hash_v1`: each envelope's hash is SHA-256 over the previous link
  concatenated with the canonical bytes of the envelope, from a fixed genesis
  link. Canonical bytes are every envelope field except the hash itself as
  sorted-key, compact, UTF-8 JSON.
- `created_at` is wall-clock at append but stored on the record and never
  regenerated, so the chain recomputes deterministically from persisted
  envelopes.
- `Session.recover` recomputes the chain before replaying and raises
  `ValueError` on a mismatch, a missing hash after the chain has started, or an
  unknown scheme. A leading run of legacy envelopes with no hash loads and is
  reported through `Session.unverified_prefix`. `Session.head_log_hash` exposes
  the current link.
- `state_hash` is unchanged and independent of `log_hash`. A `provenance`
  edit moves the log hash but not the state hash, and the architecture page now
  describes three identities: state hash, position digest, log hash.
- The honest limit is pinned by a test: a consistent rewrite of a whole suffix
  passes the chain but cannot keep the head hash, so a head recorded out of
  band still exposes it.
- The file-backed store tutorial gained chain verification without changing
  its code, because its rows come from `to_dict()`.
- New invariants INV-H1 (tamper evidence) and INV-H2 (replay determinism).

## Release and docs (PRs #15, #16)

- Version bumped to 0.2.0, changelog entries moved under a dated heading with
  compare links, `v0.2.0` tagged and a GitHub release published.
- The README's Docs section now leads with the published site at
  <https://meadowlark-bradsher.github.io/CMBS/>. The Pages deploy that used to
  fail at the deploy step now succeeds on every push to `main`; the site was
  verified live and current after the release.

## Decisions worth remembering

- New snapshot fields enter the state hash only when non-empty. This is the
  rule that kept v1 hashes stable through three feature PRs.
- Budget limits live in `check`, never in `apply`, so limits never change
  replay and never need to be persisted.
- `log_hash` and `state_hash` answer different questions and stay separate.
- Rejections are always logged with a reason, including budget refusals and
  the retired op types, so every refused attempt is auditable.
- `admit`, the open-world op that lets a hypothesis enter after the session
  starts, stays deferred. Nothing on `main` starts it.

## Housekeeping on 12 November

With the release work merged, the repository was tidied: the eight worktrees
and twelve local branches left behind by merged or discussion-only sessions
were removed, seven merged remote branches were deleted, the main checkout was
fast-forwarded to the release, and ten finished Code sessions were archived.
The repository now has one remote branch.
