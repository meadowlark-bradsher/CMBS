# Tutorials

The [`tutorials/`](https://github.com/meadowlark-bradsher/CMBS/tree/main/tutorials)
directory holds six runnable scripts, each built around one idea. Three of
them can drive the investigation with Claude through the official
`anthropic` SDK; the rest need nothing beyond the package.

| Tutorial | What it shows | LLM |
|---|---|---|
| [01 Kernel basics](https://github.com/meadowlark-bradsher/CMBS/blob/main/tutorials/01_kernel_basics.py) | The five facade calls, what the kernel books, what it refuses, and recovery from the store | no |
| [02 Twenty Questions](https://github.com/meadowlark-bradsher/CMBS/blob/main/tutorials/02_llm_twenty_questions.py) | Claude picks the questions. It is shown every question, asked or not, so INV-3 does the non-repetition work the prompt is not asked to do | optional |
| [03 Incident triage](https://github.com/meadowlark-bradsher/CMBS/blob/main/tutorials/03_llm_incident_triage.py) | Claude picks the checks. An obligation refuses an early exit and a stability window refuses an early termination | optional |
| [04 Two agents](https://github.com/meadowlark-bradsher/CMBS/blob/main/tutorials/04_convergence_two_agents.py) | Two sessions with different probe orders. `state_hash` never agrees; `position_digest` agrees when beliefs do, and names the meet when they do not | optional |
| [05 Audit and replay](https://github.com/meadowlark-bradsher/CMBS/blob/main/tutorials/05_audit_and_replay.py) | A reviewer rebuilds state from a handed-over log with the same reducer, matches the claimed hash, then catches a tampered envelope | no |
| [06 File-backed store](https://github.com/meadowlark-bradsher/CMBS/blob/main/tutorials/06_file_backed_store.py) | A JSONL `OpLogStore` implementation short enough to read in one sitting; recovery after a simulated restart | no |

## Running live

```bash
pip install -e '.[tutorials]'
export ANTHROPIC_API_KEY=...        # or: ant auth login
python tutorials/02_llm_twenty_questions.py --secret dolphin
```

Credentials resolve the way the SDK resolves them: `ANTHROPIC_API_KEY`,
`ANTHROPIC_AUTH_TOKEN`, or an `ant auth login` profile. The model defaults
to `claude-opus-5`; set `CMBS_TUTORIAL_MODEL` to change it. Every decision
is one short request at low effort with a JSON schema constraining the
reply, so a full run costs a few cents.

## Running offline

With no key, with `--offline`, or with `CMBS_TUTORIAL_OFFLINE=1`, the LLM
tutorials use a scripted policy that picks the first unasked probe. The
kernel's behavior is identical either way; only the chooser changes. The
test suite runs every tutorial offline.

## The shape they share

Each LLM tutorial separates three roles that the kernel keeps apart:

1. A **policy** decides what to probe next. That is the LLM, or the scripted
   stand-in. It sees the frontier and a list of probes and returns one.
2. An **adapter** turns an outcome into an elimination set. The shipped
   twenty-questions and ITBench adapters do this from their kit files.
3. The **`Session`** books the elimination, refuses repeats, tracks
   obligations, and keeps the log.

The policy never touches the session directly, and the session never sees
a prompt. That boundary is the point of the library; the tutorials make it
visible by letting you swap the policy with a flag.
