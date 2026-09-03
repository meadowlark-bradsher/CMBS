"""The shipped examples run end to end against the unified kernel."""

import sys
from pathlib import Path

import pytest

from cmbs import Session

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
if str(EXAMPLES) not in sys.path:
    sys.path.insert(0, str(EXAMPLES))

import run_20q  # noqa: E402
import run_itbench  # noqa: E402


def test_twenty_questions_narrows_to_the_secret():
    session = run_20q.run(secret="eagle")
    assert session.survivors == {"eagle"}
    assert session.ontology.hypothesis_space_id == "20q"
    ops = session.operations()
    assert ops and all(op.op_type == "probe_result" and op.accepted for op in ops)
    assert all(op.source_id == "adapter://twenty_questions" for op in ops)
    assert ops[0].payload["provenance"]["outcome"] in {"yes", "no"}


@pytest.mark.parametrize(
    ("secret", "expected"),
    [
        ("shark", {"shark"}),
        ("snake", {"snake"}),
        ("eagle", {"eagle"}),
        # The 20q_8 kit has no question separating the land mammals, so
        # the adapter runs out of informative actions and stops there.
        ("dog", {"dog", "cat", "horse", "cow"}),
    ],
)
def test_twenty_questions_narrows_as_far_as_the_kit_allows(secret, expected):
    session = run_20q.run(secret=secret, kit_name="20q_8")
    assert session.survivors == expected
    assert secret in session.survivors


def test_itbench_scenario_narrows_to_one_cause():
    session = run_itbench.run()
    assert len(session.survivors) == 1
    assert session.entropy == 0.0
    assert session.head_seq >= 1


def test_example_log_replays_to_the_same_state():
    session = run_20q.run(secret="shark")
    replayed = session.reducer.reduce(
        session.initial_hypotheses,
        session.operations(),
        session_id=session.session_id,
        stability_window=session.stability_window,
    )
    assert replayed == session.snapshot()


def test_examples_main_prints_summary(capsys):
    run_20q.main()
    run_itbench.main()
    out = capsys.readouterr().out
    assert "survivors: ['eagle']" in out
    assert out.count("state_hash:") == 2


def test_session_import_from_package_root():
    assert Session.__module__ == "cmbs.session"
