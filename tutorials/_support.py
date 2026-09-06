"""
Shared plumbing for the CMBS tutorials.

Every tutorial that needs a decision-maker asks a ``ProbePolicy`` for the
next action. Two implementations ship:

- ``ClaudePolicy`` calls the Claude API through the official ``anthropic``
  SDK and asks for a JSON answer that matches a schema. It resolves
  credentials the way the SDK does: ``ANTHROPIC_API_KEY``,
  ``ANTHROPIC_AUTH_TOKEN``, or an ``ant auth login`` profile.
- ``ScriptedPolicy`` picks the first still-informative action. It needs no
  network and is what the test suite runs.

``make_policy()`` chooses between them. It goes scripted when
``CMBS_TUTORIAL_OFFLINE=1`` is set, when ``--offline`` is passed, or when no
credential source is visible.

The kernel never sees any of this. A policy only decides *what to probe*;
the ``Session`` books the consequences.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

DEFAULT_MODEL = os.environ.get("CMBS_TUTORIAL_MODEL", "claude-opus-5")


@dataclass(frozen=True)
class Choice:
    """One selectable action, as the policy sees it."""

    action_id: str
    prompt: str
    already_asked: bool = False


@dataclass
class Decision:
    """What a policy returned. ``raw`` keeps the model's full answer for the log."""

    action_id: str
    reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class ProbePolicy(Protocol):
    name: str

    def choose(
        self,
        *,
        task: str,
        survivors: Sequence[str],
        choices: Sequence[Choice],
        history: Sequence[str],
    ) -> Decision: ...


class ScriptedPolicy:
    """Deterministic stand-in: first choice not yet asked, else the first choice."""

    name = "scripted"

    def choose(self, *, task, survivors, choices, history) -> Decision:
        for c in choices:
            if not c.already_asked:
                return Decision(action_id=c.action_id, reason="first unasked action")
        return Decision(action_id=choices[0].action_id, reason="nothing left; repeating")


class ClaudePolicy:
    """Ask Claude for the next action as schema-constrained JSON.

    Uses ``output_config.format`` so the reply is guaranteed to be a JSON
    object with an ``action_id`` from the offered list and a one-sentence
    ``reason``. Effort is ``low``: choosing among a handful of probes is
    not a hard problem and the tutorials should be cheap to run.

    Refusal fallbacks are enabled by default (``fallbacks="default"`` with
    the matching beta header), so a safety decline is re-run on a fallback
    model inside the same call instead of failing the tutorial. Drop the
    two lines marked ``fallback`` if you would rather see the refusal.
    """

    name = "claude"

    SYSTEM = (
        "You are the probe-selection policy for a hypothesis-elimination "
        "investigation. You will be shown the surviving hypotheses and a list "
        "of probes. Pick the single probe that best splits the survivors. "
        "Never pick a probe marked already_asked unless nothing else remains. "
        "Reply with JSON only."
    )

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        import anthropic  # imported here so the offline path needs no SDK

        self._anthropic = anthropic
        self._client = anthropic.Anthropic()
        self.model = model
        self.calls = 0

    def choose(self, *, task, survivors, choices, history) -> Decision:
        allowed = [c.action_id for c in choices]
        schema = {
            "type": "object",
            "properties": {
                "action_id": {"type": "string", "enum": allowed},
                "reason": {"type": "string"},
            },
            "required": ["action_id", "reason"],
            "additionalProperties": False,
        }
        user = json.dumps(
            {
                "task": task,
                "survivors": sorted(survivors),
                "probes": [
                    {"action_id": c.action_id, "prompt": c.prompt, "already_asked": c.already_asked}
                    for c in choices
                ],
                "history": list(history),
            },
            indent=2,
        )
        response = self._client.beta.messages.create(
            model=self.model,
            max_tokens=1024,
            system=self.SYSTEM,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"],  # fallback
            fallbacks="default",  # fallback
        )
        self.calls += 1
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise RuntimeError(f"Claude declined the request: {details}")
        text = next(b.text for b in response.content if b.type == "text")
        data = json.loads(text)
        return Decision(action_id=data["action_id"], reason=data.get("reason", ""), raw=data)


def credentials_visible() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return (Path.home() / ".config" / "anthropic").exists()


def make_policy(argv: Sequence[str] | None = None, *, quiet: bool = False) -> ProbePolicy:
    """Pick ``ClaudePolicy`` when a key is available, else ``ScriptedPolicy``."""
    args = list(sys.argv[1:] if argv is None else argv)
    offline = "--offline" in args or os.environ.get("CMBS_TUTORIAL_OFFLINE") == "1"
    if not offline and credentials_visible():
        try:
            policy: ProbePolicy = ClaudePolicy()
        except ImportError:
            if not quiet:
                print("anthropic SDK not installed; run `pip install 'cmbs[tutorials]'`. "
                      "Using the scripted policy.")
            return ScriptedPolicy()
        if not quiet:
            print(f"policy: Claude ({policy.model})")
        return policy
    if not quiet:
        why = "--offline" if offline else "no ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or ant profile found"
        print(f"policy: scripted ({why})")
    return ScriptedPolicy()


def banner(title: str) -> None:
    print()
    print(title)
    print("=" * len(title))


def show(label: str, value: Any) -> None:
    print(f"  {label:<22} {value}")
