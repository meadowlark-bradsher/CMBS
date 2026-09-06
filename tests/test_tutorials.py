"""The tutorials run end to end with the scripted policy (no network, no key)."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

TUTORIALS = Path(__file__).resolve().parents[1] / "tutorials"
if str(TUTORIALS) not in sys.path:
    sys.path.insert(0, str(TUTORIALS))


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("CMBS_TUTORIAL_OFFLINE", "1")


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, TUTORIALS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve postponed annotations via sys.modules
    spec.loader.exec_module(module)
    return module


def test_support_picks_scripted_policy_offline(capsys):
    support = load("_support")
    policy = support.make_policy([])
    assert policy.name == "scripted"
    assert "scripted" in capsys.readouterr().out


def test_support_offline_flag_wins_even_with_a_key(monkeypatch):
    support = load("_support")
    monkeypatch.delenv("CMBS_TUTORIAL_OFFLINE")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    assert support.make_policy(["--offline"], quiet=True).name == "scripted"


def _norm(text: str) -> str:
    return " ".join(text.split())


def test_01_kernel_basics(capsys):
    session = load("01_kernel_basics").run()
    assert session.is_terminated
    assert session.survivors == {"replication_lag"}
    out = _norm(capsys.readouterr().out)
    assert "REJ probe_result" in out
    assert "same state_hash True" in out


@pytest.mark.parametrize("secret", ["eagle", "shark", "snake"])
def test_02_twenty_questions_offline(secret):
    mod = load("02_llm_twenty_questions")
    support = load("_support")
    session = mod.run(support.ScriptedPolicy(), secret=secret)
    assert secret in session.survivors
    assert all(op.accepted for op in session.operations())


def test_02_repeat_question_is_rejected_by_the_kernel():
    mod = load("02_llm_twenty_questions")
    Decision = load("_support").Decision

    class Stubborn:
        name = "stubborn"

        def choose(self, *, task, survivors, choices, history):
            return Decision(action_id=choices[0].action_id, reason="always the first")

    session = mod.run(Stubborn(), secret="eagle", max_turns=3)
    ops = session.operations()
    assert [op.accepted for op in ops] == [True, False, False]
    assert all("duplicate" in op.rejected_reason for op in ops[1:])


def test_03_incident_triage_offline(capsys):
    mod = load("03_llm_incident_triage")
    session = mod.run(load("_support").ScriptedPolicy())
    assert session.is_terminated
    assert session.active_obligations == frozenset()
    out = _norm(capsys.readouterr().out)
    assert "exit permitted False" in out  # the early exit was refused
    assert "exit permitted True" in out  # and the earned exit was allowed
    assert "terminate after 1 False" in out


def test_04_convergence_offline():
    mod = load("04_convergence_two_agents")
    a, b = mod.run(load("_support").ScriptedPolicy(), secret="shark")
    assert a.survivors == b.survivors == {"shark"}
    assert a.position_digest == b.position_digest
    assert a.snapshot().state_hash != b.snapshot().state_hash


def test_05_audit_and_replay(capsys):
    load("05_audit_and_replay").run()
    out = _norm(capsys.readouterr().out)
    assert out.count("hash matches claim True") == 1
    assert out.count("hash matches claim False") == 1
    assert "other digest equal True" in out


def test_06_file_backed_store(tmp_path):
    recovered, reread = load("06_file_backed_store").run(tmp_path)
    assert recovered.survivors == {"H3"}
    assert reread.snapshot() == recovered.snapshot()
    assert (tmp_path / "durable-1.jsonl").exists()
    assert os.path.getsize(tmp_path / "durable-1.jsonl") > 0


def test_claude_policy_import_is_lazy():
    """The offline path must not require the anthropic SDK: the only import
    of it lives inside ClaudePolicy, not at module top level."""
    src = (TUTORIALS / "_support.py").read_text()
    top, inside = src.split("class ClaudePolicy")
    assert "import anthropic" not in top
    assert "import anthropic" in inside
