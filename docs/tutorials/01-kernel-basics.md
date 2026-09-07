# 01 · Kernel basics

No LLM, no adapters. One `Session`, the five facade calls, and a look at
what the kernel books, what it refuses, and what it can rebuild. Everything
later in the series is a variation on the moves made here.

## Run it

```bash
python tutorials/01_kernel_basics.py
```

Nothing to configure. It finishes in well under a second.

## Walkthrough

The script opens a session over four candidate root causes with a
stability window of two, and keeps the store in a variable so it can
recover from it at the end.

```python
store = InMemoryOpLogStore()
session = Session(
    hypothesis_ids={"disk_full", "bad_deploy", "replication_lag", "network_partition"},
    stability_window=2,  # INV-2: two identical conclusions before termination
    store=store,
)
```

### 1. A fresh session is the top of the lattice

```
survivors              ['bad_deploy', 'disk_full', 'network_partition', 'replication_lag']
entropy (bits)         2.0
position_digest        c30549b17ff11326…
```

Four survivors, two bits. The position digest names this survivor set and
nothing else; any session over these four IDs starts with the same digest.

### 2. Probes eliminate, and the kernel trusts the caller's set

```python
r = session.submit_probe_result(
    probe_id="check_disk", observable_id="disk_usage=41%", eliminated={"disk_full"}
)
```

```
accepted               True
newly eliminated       ['disk_full']
survivors              ['bad_deploy', 'network_partition', 'replication_lag']
```

The kernel does not know what `disk_usage=41%` means or why it rules out
`disk_full`. That interpretation is the caller's. The kernel records the
observable ID, applies the set, and moves on.

### 3. INV-3: the same probe ID is refused, and the attempt is logged

```python
r = session.submit_probe_result(
    probe_id="check_disk", observable_id="disk_usage=41%", eliminated={"bad_deploy"}
)
```

```
accepted               False
error                  duplicate idempotency_key: 'check_disk'
survivors              ['bad_deploy', 'network_partition', 'replication_lag']
log length             2
```

Same probe ID, a different elimination set, and the kernel refuses it.
Nothing changed in the survivors. The log length went from one to two:
the refusal is an envelope too, with the reason on it.

### 4. INV-6: an obligation gates its own exit on eliminations in scope

```python
session.enter_obligation("triage", min_eliminations=2)
show("exit before work", session.request_obligation_exit("triage").permitted)
# ... one probe eliminating bad_deploy ...
show("exit after one", session.request_obligation_exit("triage").permitted)
# ... one probe eliminating network_partition ...
show("exit after two", session.request_obligation_exit("triage").permitted)
```

```
exit before work       False
exit after one         False
exit after two         True
survivors              ['replication_lag']
```

The obligation was opened *after* `disk_full` was eliminated, so that
elimination does not count toward it. Only the two that happened inside
the obligation's scope do. This is what stops an agent from declaring an
investigation finished on the strength of work it did before starting it.

### 5. INV-2: termination waits for a stable conclusion

```python
session.declare_conclusion("replication_lag")
show("terminate after one", session.request_termination().permitted)
session.declare_conclusion("replication_lag")
show("terminate after two", session.request_termination().permitted)
```

```
terminate after one    False
terminate after two    True
is_terminated          True
```

The window was set to two at construction. One declaration is not
enough; two identical ones in a row are. A different conclusion in
between would have reset the count.

### 6. The log is the audit trail, including the refusals

```
 1 ok  probe_result
 2 REJ probe_result         duplicate idempotency_key: 'check_disk'
 3 ok  enter_obligation
 4 REJ exit_obligation      insufficient eliminations in scope for 'triage': 0 of 2 required
 5 ok  probe_result
 6 REJ exit_obligation      insufficient eliminations in scope for 'triage': 1 of 2 required
 7 ok  probe_result
 8 ok  exit_obligation
 9 ok  declare_conclusion
10 REJ request_termination  conclusion history shorter than stability window: 1 of 2 required
11 ok  declare_conclusion
12 ok  request_termination
```

Twelve envelopes for twelve calls. Every refusal is there with its reason.
A reviewer reading this log later knows not only what the investigation
concluded but every time it tried to cut a corner and was stopped.

### 7. Recovery is replay

```python
again = Session.recover(store, session.session_id)
```

```
same snapshot          True
same state_hash        True
```

The recovered session was built by folding the twelve envelopes through
the reducer. It equals the original in every field, hash included.

## What to notice

- **Rejections cost nothing and hide nothing.** The kernel never raises on
  a refused facade call. It returns a result with `permitted` or
  `accepted` set to false, the reason attached, and a new line in the log.
- **Scope is temporal.** Obligations count eliminations from the moment
  they open. Nothing before that counts, no matter how relevant.
- **State is not stored, it is derived.** Step 7 is not deserialization.
  It is the same computation the session has been doing on every append.

## Source

[`tutorials/01_kernel_basics.py`](https://github.com/meadowlark-bradsher/CMBS/blob/main/tutorials/01_kernel_basics.py)

Next: [02 · Twenty Questions](02-twenty-questions.md), where an LLM
decides which probe to run.
