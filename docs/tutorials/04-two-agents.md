# 04 · Two agents

Two agents investigate the same universe in separate sessions with
different probe orders. Their session IDs, logs, and state hashes all
differ, by construction and forever. `position_digest` is the thing that
agrees when their *beliefs* agree, so they can check convergence without
exchanging logs. When they disagree, the meet of their two frontiers is
itself a position, and the digest names it.

## Run it

```bash
python tutorials/04_convergence_two_agents.py
python tutorials/04_convergence_two_agents.py --offline
```

With a key visible, agent A is Claude and agent B is scripted with the
question list reversed. Offline, both are scripted, one in kit order and
one reversed.

## Walkthrough

### Two sessions, one universe

```python
a = Session(hypothesis_ids=kit.hypotheses, session_id="agent-a")
b = Session(hypothesis_ids=kit.hypotheses, session_id="agent-b")
order_a, order_b = list(kit.actions_order), list(reversed(kit.actions_order))
```

Each agent has its own adapter instance and its own list of what it has
asked. The oracle is shared because the secret is the same; nothing else
is.

### Stepping them in lockstep

Each step lets both agents ask one question, then compares digests:

```python
same = a.position_digest == b.position_digest
if not same:
    meet = a.survivors & b.survivors
    print(f"meet = {sorted(meet)}  digest {compute_position_digest(meet)[:8]}")
```

```
step  A asked        B asked        A digest   B digest   same?
1     is_mammal      is_domestic    352a9736   b512a139   no
      meet = ['eagle', 'shark', 'snake']  digest 352a9736
2     is_aquatic     is_reptile     aadf028b   4ce8d537   no
      meet = ['shark']  digest aadf028b
3     -              is_flying      aadf028b   e9f66ff7   no
      meet = ['shark']  digest aadf028b
4     -              is_aquatic     aadf028b   e9f66ff7   no
      meet = ['shark']  digest aadf028b
5     -              is_mammal      aadf028b   aadf028b   yes
```

Read the table by column. Agent A reaches `shark` in two questions and
stops. Agent B, asking in reverse order, needs five. Their digests differ
at every step until B catches up, and then they match exactly.

The meet column is worth a second look. At step 1 the meet equals A's
digest: A's belief is already contained in B's, so the intersection is
just A's frontier. From step 2 on the meet is `shark` with A's digest,
because A is already there. The meet is always at least as narrow as
either agent, and its digest is a real position that a third session
could reach and compare against.

### Where they ended up

```
A survivors            ['shark']
B survivors            ['shark']
A state_hash           74aa9c6b3e4218b9…
B state_hash           49d677ceec8a18a6…
state hashes equal     False
position digests equal True
```

The state hashes will never be equal: different session IDs, different
log lengths, different histories. The position digests are equal because
the survivor sets are, and that is the question "have we converged?"
actually asks.

## What to notice

- **Convergence needs no log exchange.** Sixty-four hex characters each
  way settle it. The logs stay private to their sessions.
- **The meet is a position, not a merge.** Intersecting two frontiers
  does not combine two logs or resolve their order. It produces a subset,
  which is a lattice point like any other. Naming it with the digest is
  cheap; constructing a session that *reaches* it is a separate step.
- **Order changes the path, not the destination.** Both agents end at
  `shark` because every question in the kit is a pure elimination, and
  pure eliminations commute. Obligations and conclusions would not
  commute, which is exactly why they are in the state hash and not in
  the digest.
- **A live run changes column A only.** Claude usually finds a shorter
  path than kit order, but the table's structure and the final agreement
  are the same.

## Source

[`tutorials/04_convergence_two_agents.py`](https://github.com/meadowlark-bradsher/CMBS/blob/main/tutorials/04_convergence_two_agents.py)

Next: [05 · Audit and replay](05-audit-and-replay.md), where a log is
handed to someone who does not trust it.
