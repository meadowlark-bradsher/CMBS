# 03 · Incident triage

LLM-driven root-cause triage with two pieces of workflow discipline on
top. The ITBench kit lists six candidate causes and six checks. Claude
picks which check to run next; a scripted scenario reports each outcome.
Before the agent is allowed to conclude, the kernel makes it earn the
right twice over:

- an obligation named `triage` must see at least three eliminations before
  the agent may leave the investigation phase (INV-6), and
- a stability window of two means a conclusion must be declared twice in a
  row before termination is permitted (INV-2).

The tutorial tries to cut both corners so you can see the refusals.

## Run it

```bash
python tutorials/03_llm_incident_triage.py
python tutorials/03_llm_incident_triage.py --offline
```

Same credential and fallback rules as tutorial 02.

## Walkthrough

### Setup

```python
session = Session(
    hypothesis_ids=kit.hypotheses,
    ontology=OntologyBundle(hypothesis_space_id="itbench", hypothesis_version=kit_name),
    stability_window=2,
)
session.enter_obligation("triage", min_eliminations=3)
```

```
candidate causes       ['bad_deploy', 'cpu_throttle', 'db_connection_exhaustion',
                        'disk_full', 'network_partition', 'replication_lag']
```

The scenario is fixed: replication lag is high and every other check comes
back normal. The policy does not know that; it sees only the survivors and
the check descriptions.

### Trying to skip the investigation

```python
early = session.request_obligation_exit("triage")
```

```
exit permitted         False
reason                 insufficient eliminations in scope for 'triage': 0 of 3 required
```

Nothing has been checked, so the obligation refuses to close. The reason
says exactly how far short the agent is.

### Investigation

Unlike tutorial 02, the choices offered here exclude checks already run,
so the loop is about ordering rather than repeats. Each iteration books
one check and prints the obligation's progress:

```python
result = session.submit_probe_result(
    probe_id=decision.action_id,
    observable_id=msg.observation_id,
    eliminated=msg.eliminated,
    source_id=f"policy://{policy.name}",
    provenance={"outcome": outcome, "reason": decision.reason},
)
entry = session.snapshot().obligation("triage")
show("triage progress", f"{entry.eliminations_in_scope}/{entry.min_eliminations}")
```

Offline, the scripted policy runs the checks in kit order:

```
Check replication lag metric  →  high
eliminated             ['bad_deploy', 'db_connection_exhaustion']
survivors              ['cpu_throttle', 'disk_full', 'network_partition', 'replication_lag']
triage progress        2/3

Check disk usage  →  ok
eliminated             ['disk_full']
survivors              ['cpu_throttle', 'network_partition', 'replication_lag']
triage progress        3/3

Compare deployed version to expected  →  expected
eliminated             nothing
survivors              ['cpu_throttle', 'network_partition', 'replication_lag']
triage progress        3/3

Check database connection saturation  →  normal
eliminated             nothing
triage progress        3/3

Check network packet loss  →  healthy
eliminated             ['network_partition']
triage progress        4/3

Check CPU throttling indicator  →  normal
eliminated             ['cpu_throttle']
survivors              ['replication_lag']
triage progress        5/3
```

Two of the six checks eliminated nothing. In this kit, the deploy-version
and connection-saturation checks only rule out causes that the first check
had already removed. The scripted policy cannot see that; a live run with
Claude typically skips them, because it can reason about which checks
still discriminate among the survivors.

### Leaving the investigation phase

```
exit permitted         True
```

Five eliminations in scope against a minimum of three. The obligation
closes and the agent may move on.

### Concluding

```python
session.declare_conclusion(conclusion)
first = session.request_termination()
session.declare_conclusion(conclusion)
second = session.request_termination()
```

```
terminate after 1      False  (conclusion history shorter than stability window: 1 of 2 required)
terminate after 2      True
conclusion             replication_lag
is_terminated          True
```

The first termination request is refused with the reason. The second, after
the same conclusion is declared again, is permitted.

## What to notice

- **Two gates, two failure modes.** The obligation stops "done before
  starting". The stability window stops "done on a single reading". They
  are independent: the obligation can be closed while termination is still
  refused, and vice versa.
- **Progress is visible in the snapshot.** `snapshot().obligation("triage")`
  returns the entry with its running count, so a policy or a UI can show
  how far the investigation is from being allowed to stop.
- **Zero-information checks are legal and logged.** The kernel accepted
  both no-op checks and counted their zero eliminations. Avoiding them is
  the policy's job; the kernel's job is to make sure they are on the
  record.
- **The kernel never saw the scenario.** It booked six outcomes it could
  not interpret and enforced two rules it could. That is the whole
  division of labor.

## Source

[`tutorials/03_llm_incident_triage.py`](https://github.com/meadowlark-bradsher/CMBS/blob/main/tutorials/03_llm_incident_triage.py)

Next: [04 · Two agents](04-two-agents.md), where two sessions have to
agree on a belief without sharing a log.
