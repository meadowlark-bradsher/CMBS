# 02 · Twenty Questions

An LLM plays Twenty Questions against the kernel. Claude chooses which
question to ask; the kit's oracle answers for a secret; the adapter turns
each answer into an elimination set; the `Session` books it.

The point of the tutorial is a boundary. The LLM is shown *every* question
in the kit, including ones it has already asked, and the prompt does not
tell it to avoid repeats beyond a mild instruction. Non-repetition is the
kernel's job (INV-3), and this tutorial lets you watch the kernel do it
rather than trusting the prompt to.

## Run it

```bash
pip install -e '.[tutorials]'
export ANTHROPIC_API_KEY=...        # or: ant auth login
python tutorials/02_llm_twenty_questions.py --secret dolphin
```

Without a key, or with `--offline`, a scripted policy that always picks the
first unasked question stands in for Claude. The kernel's behavior is
identical; only the chooser changes. Every Claude decision is one short
request at low effort with a JSON schema on the reply, so a game costs a
few cents. See the [overview](index.md) for credential resolution and
the model override.

## Walkthrough

### The three roles

```python
kit = load_builtin_kit(kit_name)       # the questions and their answer tables
adapter = TwentyQAdapter(kit)          # answer  →  elimination set
oracle = TwentyQOracle(kit)            # answers for the secret
session = Session(
    hypothesis_ids=kit.hypotheses,
    ontology=OntologyBundle(hypothesis_space_id="20q", hypothesis_version=kit_name),
)
```

The policy is the fourth piece. `make_policy()` in `_support.py` returns
either `ClaudePolicy` or `ScriptedPolicy`; both expose one method,
`choose(...)`, that takes the survivors and a list of probes and returns
a `Decision` with an `action_id`.

### What Claude is shown

On every turn the policy receives all five questions from the `20q_8` kit,
each flagged with whether it has been asked:

```python
choices = [
    Choice(action_id=aid, prompt=kit.actions[aid].question, already_asked=aid in asked)
    for aid in kit.actions_order
]
decision = policy.choose(
    task="Identify the secret animal with as few questions as possible.",
    survivors=sorted(session.survivors),
    choices=choices,
    history=asked,
)
```

The reply is constrained by a JSON schema whose `action_id` is an enum of
exactly those five IDs. Claude selects; it never invents a question. It is
not shown the kit's answer tables, so any prediction it makes about how a
question will split the survivors comes from its own knowledge of animals.

### Booking the answer

```python
ctx = adapter.apply_action(decision.action_id, session.snapshot())
(msg,) = adapter.observe(ctx, answer)
result = session.submit_probe_result(
    probe_id=decision.action_id,  # the question is the probe; re-asking is a repeat
    observable_id=msg.observation_id,
    eliminated=msg.eliminated,
    source_id=f"policy://{policy.name}",
    provenance={"question": question, "answer": answer, "reason": decision.reason},
)
```

The probe ID is the question ID, not the question-plus-answer, so asking
the same question again is a repeat whatever the answer. Claude's stated
reason goes into the envelope's provenance, where the kernel stores it
verbatim and never reads it.

### A live game

This is a real run with the secret `dolphin`, Claude on `claude-opus-5`:

```
turn 1: Is it a mammal?  →  yes
  reason: Mammals (cat, cow, dog, dolphin, horse) vs non-mammals (eagle, shark,
  snake) gives a 5-3 split, the most balanced division available; other probes
  isolate far fewer (flying 1, reptile 1, aquatic 2, domestic 4-4 but domestic
  also splits 4-4). Mammal is a robust, unambiguous split.
eliminated             ['eagle', 'shark', 'snake']
survivors              ['cat', 'cow', 'dog', 'dolphin', 'horse']

turn 2: Is it commonly domesticated?  →  no
  reason: All survivors are mammals; domestication splits them 4 (cat, cow, dog,
  horse) vs 1 (dolphin), same as aquatic, but domestic is the most informative
  remaining non-redundant probe since flying and reptile eliminate nothing.
eliminated             ['cat', 'cow', 'dog', 'horse']
survivors              ['dolphin']

Result
======
survivors              ['dolphin']
secret survived        True
ops in log             2
rejected attempts      0
```

Nobody told Claude to reason about information. The prompt said "best
splits the survivors" and "as few questions as possible", the survivor
list was short enough to count, and Twenty Questions is a problem whose
known strategy is to halve the space. It also noticed on turn two that
the flying and reptile questions would eliminate nothing among mammals.
The kernel would have accepted a zero-information question and logged it;
skipping it was the policy's judgment alone.

The same secret offline, with the scripted policy:

```
turn 1: Is it a mammal?  →  yes
turn 2: Does it live in water?  →  yes
survivors              ['dolphin']
```

Same kernel, same adapter, a different chooser.

### What a repeat looks like

If a policy insists on a question it already asked, the kernel refuses
and the turn is spent:

```
turn 2: Is it a mammal?  →  yes
  REJECTED by the kernel: duplicate idempotency_key: 'is_mammal'
```

The survivors do not change, a rejected envelope enters the log, and
the loop continues. The test suite drives this with a deliberately
stubborn policy and asserts the second and third attempts are refused.

## What to notice

- **Selection, not generation.** The kit owns the questions and the
  answer tables. The LLM ranks them. That split is what makes the
  reasoning come out as strategy rather than trivia.
- **The prompt is not the safety net.** It says not to repeat, but the
  guarantee comes from the kernel and holds for any policy, including a
  broken one.
- **World knowledge used, not trusted.** Claude predicted the 5-3 split
  from what it knows about mammals, but only the kit's table eliminated
  anything.
- **Watch `position_digest`.** The script prints a note when a question
  eliminates nothing, which is the digest staying the same across a turn.

## Source

[`tutorials/02_llm_twenty_questions.py`](https://github.com/meadowlark-bradsher/CMBS/blob/main/tutorials/02_llm_twenty_questions.py)
and the shared
[`tutorials/_support.py`](https://github.com/meadowlark-bradsher/CMBS/blob/main/tutorials/_support.py).

Next: [03 · Incident triage](03-incident-triage.md), which adds an
obligation and a stability window on top of the same loop.
