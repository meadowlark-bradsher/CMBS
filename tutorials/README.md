# CMBS tutorials

Six runnable scripts, each one idea. Run them from the repository root.

| Script | What it shows | Needs an LLM? |
|---|---|---|
| `01_kernel_basics.py` | The five facade calls, what the kernel books, what it refuses, recovery | no |
| `02_llm_twenty_questions.py` | Claude picks questions; INV-3 refuses a repeat the prompt did not prevent | optional |
| `03_llm_incident_triage.py` | Claude picks checks; an obligation and a stability window gate the exit and the conclusion | optional |
| `04_convergence_two_agents.py` | Two sessions, different orders, `position_digest` agrees when beliefs agree | optional |
| `05_audit_and_replay.py` | A reviewer replays a handed-over log and catches a tampered envelope | no |
| `06_file_backed_store.py` | A JSONL `OpLogStore` in forty lines; recover after a "restart" | no |

## Running live

The LLM tutorials use the official `anthropic` SDK and resolve credentials
the way it does: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, or a profile
from `ant auth login`. Install the SDK with the package extra:

```bash
pip install -e '.[tutorials]'
export ANTHROPIC_API_KEY=...        # or: ant auth login
python tutorials/02_llm_twenty_questions.py --secret dolphin
```

The model defaults to `claude-opus-5`; set `CMBS_TUTORIAL_MODEL` to change it.
Each decision is one short request at low effort with a JSON schema on the
reply, so a full tutorial is a handful of cents. Refusal fallbacks are on by
default; see `ClaudePolicy` in `_support.py` to turn them off.

## Running offline

Without a key, or with `--offline`, or with `CMBS_TUTORIAL_OFFLINE=1`, the
LLM tutorials use a scripted policy that picks the first unasked probe. The
kernel behavior is identical; only the chooser changes. The test suite runs
every tutorial this way.

## Writing your own

Copy `_support.py`'s `ProbePolicy` shape: a `choose(...)` that returns a
`Decision`. Everything the kernel needs is on the `Session`; the policy
only decides what to probe next.
