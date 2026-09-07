# 05 · Audit and replay

The log as evidence. An investigator hands a reviewer the initial
hypothesis set and the op log. The reviewer rebuilds the state
independently with the same reducer and compares hashes, then we tamper
with one envelope and watch the comparison fail.

No LLM involved.

## Run it

```bash
python tutorials/05_audit_and_replay.py
```

## Walkthrough

The script builds a short session with one refusal in it, so the log has
something interesting to carry.

```python
session = Session(hypothesis_ids={"H1", "H2", "H3", "H4"}, session_id="case-42")
session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
session.enter_obligation("review", min_eliminations=1)
session.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={"H3"})
session.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={"H4"})  # rejected
session.request_obligation_exit("review")
session.declare_conclusion("H2-or-H4")
```

### 1. What the investigator hands over

```python
handoff = {
    "session_id": session.session_id,
    "initial_hypotheses": sorted(session.initial_hypotheses),
    "stability_window": session.stability_window,
    "reducer_version": session.reducer.version,
    "claimed_state_hash": session.snapshot().state_hash,
    "ops": [op.to_dict() for op in session.operations()],
}
wire = json.dumps(handoff)
```

```
bytes on the wire      1834
claimed state_hash     07bdcc10584e1c99…
```

Nothing in the handoff is a `Session` object. It is the starting universe,
the configuration the reducer needs, the claimed final hash, and the
envelopes as plain dictionaries. A different process, language, or
organization can consume it.

### 2. The reviewer replays it independently

```python
received = json.loads(wire)
envelopes = [OperationEnvelope(**d) for d in received["ops"]]
replayed = MaskMeetTombstoneReducer().reduce(
    received["initial_hypotheses"],
    envelopes,
    session_id=received["session_id"],
    stability_window=received["stability_window"],
)
```

```
replayed survivors     ['H2', 'H4']
hash matches claim     True
 1 ok  probe_result
 2 ok  enter_obligation
 3 ok  probe_result
 4 REJ probe_result         duplicate idempotency_key: 'P2'
 5 ok  exit_obligation
 6 ok  declare_conclusion
```

The reviewer never trusted the investigator's survivors. They computed
their own from the log and got the same hash. The rejected envelope at
seq 4 came along for the ride: the reviewer can see that a repeat was
attempted and refused.

### 3. Tampering with one envelope breaks the chain

```python
tampered = list(envelopes)
first_probe = tampered[0]  # seq 1: the probe that eliminated H1
tampered[0] = replace(first_probe, payload={**first_probe.payload, "eliminate": ["H1", "H2"]})
```

```
tampered survivors     ['H4']
hash matches claim     False
```

One extra ID in one elimination list. The replayed state now has one
survivor instead of two, and the hash no longer matches the claim. There
is no separate signature to check; the claim *is* a hash of the content,
so any change to the content is a change to the claim.

### 4. Two hashes, two questions

```
state_hash             which position in THIS log?
position_digest        which point in the lattice?
other state_hash equal False
other digest equal     True
```

A second session, `case-99`, reaches the same two survivors by a
different route: one probe instead of two, no obligation, no conclusion.
Its state hash differs from `case-42`'s because the history and the
session ID differ. Its position digest is identical because the belief
is identical. Use the first for audit and the second for convergence.

## What to notice

- **The reducer version travels with the log.** The reviewer must replay
  under the same version, and `Session.recover` refuses a mismatch. A
  replay under a different reducer is a different computation, not a
  verification.
- **Rejected envelopes are part of the evidence.** They are not noise to
  strip before sending. A log with the refusals removed would hash
  differently and would hide the investigation's near-misses.
- **The universe is part of the handoff.** The digest ignores it, but the
  replay cannot start without it.

## Source

[`tutorials/05_audit_and_replay.py`](https://github.com/meadowlark-bradsher/CMBS/blob/main/tutorials/05_audit_and_replay.py)

Next: [06 · File-backed store](06-file-backed-store.md), which puts the
log on disk.
