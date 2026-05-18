import pytest

from cmbs.op_models import OperationSpec
from cmbs.oplog_server import OplogServer, OplogServerError


def _new_session(server: OplogServer) -> str:
    created = server.create_session(
        ontology={
            "hypothesis_space_id": "test",
            "hypothesis_version": "v1",
            "causal_graph_ref": "none",
            "causal_graph_version": "v0",
        },
        initial_hypotheses=["H1", "H2", "H3"],
    )
    return created["sid"]


def test_v2_append_idempotent_by_key():
    server = OplogServer()
    sid = _new_session(server)

    first = server.append_op(
        sid=sid,
        branch_id="main",
        spec=OperationSpec(
            op_id=None,
            op_type="retract",
            payload={"eliminate": ["H1"]},
            source_id="test",
            idempotency_key="k1",
        ),
    )
    second = server.append_op(
        sid=sid,
        branch_id="main",
        spec=OperationSpec(
            op_id=None,
            op_type="retract",
            payload={"eliminate": ["H1"]},
            source_id="test",
            idempotency_key="k1",
        ),
    )

    assert first.seq == second.seq
    assert second.branch_head_seq == 1
    ops = server.get_ops(sid, "main")
    assert len(ops["ops"]) == 1


def test_v2_rejected_op_is_logged_but_not_applied():
    server = OplogServer()
    sid = _new_session(server)

    rejected = server.append_op(
        sid=sid,
        branch_id="main",
        spec=OperationSpec(
            op_id="op-reject",
            op_type="retract",
            payload={"eliminate": ["H1"]},
            source_id="test",
            preconditions=["survivors_contains:H9"],
        ),
    )

    assert rejected.accepted is False
    state = server.get_state(sid, branch="main", at=None, reducer="v1_mask_meet_tombstone")
    assert set(state["state_projection"]["survivors"]) == {"H1", "H2", "H3"}
    ops = server.get_ops(sid, "main")
    assert len(ops["ops"]) == 1
    assert ops["ops"][0]["accepted"] is False


def test_v2_state_at_seq_matches_prefix_replay():
    server = OplogServer()
    sid = _new_session(server)

    server.append_op(
        sid=sid,
        branch_id="main",
        spec=OperationSpec(
            op_id="o1",
            op_type="retract",
            payload={"eliminate": ["H1"]},
            source_id="test",
        ),
    )
    server.append_op(
        sid=sid,
        branch_id="main",
        spec=OperationSpec(
            op_id="o2",
            op_type="retract",
            payload={"eliminate": ["H2"]},
            source_id="test",
        ),
    )

    at1 = server.get_state(sid, branch="main", at=1, reducer="v1_mask_meet_tombstone")
    at2 = server.get_state(sid, branch="main", at=2, reducer="v1_mask_meet_tombstone")

    assert set(at1["state_projection"]["survivors"]) == {"H2", "H3"}
    assert set(at2["state_projection"]["survivors"]) == {"H3"}


def test_v2_commutativity_probe_detects_order_sensitivity():
    server = OplogServer()
    sid = _new_session(server)

    result = server.analyze_commute(
        sid=sid,
        branch="main",
        seq=0,
        reducer="v1_mask_meet_tombstone",
        op_a=OperationSpec(
            op_id="a",
            op_type="assert",
            payload={"set": {"root": "db"}},
            source_id="test",
        ),
        op_b=OperationSpec(
            op_id="b",
            op_type="refine",
            payload={"if_attr": "root", "equals": "db", "eliminate": ["H2"]},
            source_id="test",
        ),
    )

    assert result["commutes"] is False
    assert result["state_hash_a_then_b"] != result["state_hash_b_then_a"]
    assert "witness" in result


def test_v2_branch_order_difference_changes_state_hash():
    server = OplogServer()
    sid = _new_session(server)

    a = server.create_branch(sid, from_branch="main", from_seq=0, name="A")
    b = server.create_branch(sid, from_branch="main", from_seq=0, name="B")

    server.append_op(
        sid=sid,
        branch_id=a["branch_id"],
        spec=OperationSpec(
            op_id="a1",
            op_type="assert",
            payload={"set": {"root": "db"}},
            source_id="test",
        ),
    )
    server.append_op(
        sid=sid,
        branch_id=a["branch_id"],
        spec=OperationSpec(
            op_id="a2",
            op_type="refine",
            payload={"if_attr": "root", "equals": "db", "eliminate": ["H2"]},
            source_id="test",
        ),
    )

    server.append_op(
        sid=sid,
        branch_id=b["branch_id"],
        spec=OperationSpec(
            op_id="b1",
            op_type="refine",
            payload={"if_attr": "root", "equals": "db", "eliminate": ["H2"]},
            source_id="test",
        ),
    )
    server.append_op(
        sid=sid,
        branch_id=b["branch_id"],
        spec=OperationSpec(
            op_id="b2",
            op_type="assert",
            payload={"set": {"root": "db"}},
            source_id="test",
        ),
    )

    state_a = server.get_state(sid, branch=a["branch_id"], at=None, reducer="v1_mask_meet_tombstone")
    state_b = server.get_state(sid, branch=b["branch_id"], at=None, reducer="v1_mask_meet_tombstone")

    assert state_a["state_hash"] != state_b["state_hash"]
    assert state_a["state_projection"]["survivors"] != state_b["state_projection"]["survivors"]


def test_v2_merge_non_commutative_returns_conflict_witness():
    server = OplogServer()
    sid = _new_session(server)

    left = server.create_branch(sid, from_branch="main", from_seq=0, name="left")
    right = server.create_branch(sid, from_branch="main", from_seq=0, name="right")

    server.append_op(
        sid=sid,
        branch_id=left["branch_id"],
        spec=OperationSpec(
            op_id="left-op",
            op_type="assert",
            payload={"set": {"root": "db"}},
            source_id="test",
        ),
    )
    server.append_op(
        sid=sid,
        branch_id=right["branch_id"],
        spec=OperationSpec(
            op_id="right-op",
            op_type="refine",
            payload={"if_attr": "root", "equals": "db", "eliminate": ["H2"]},
            source_id="test",
        ),
    )

    with pytest.raises(OplogServerError) as exc_info:
        server.merge(
            sid=sid,
            base_branch="main",
            base_seq=0,
            heads=[
                {"branch": left["branch_id"], "seq": 1},
                {"branch": right["branch_id"], "seq": 1},
            ],
            policy="refuse_non_commutative",
            reducer="v1_mask_meet_tombstone",
        )
    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.code == "NON_COMMUTATIVE_CONFLICT"
    assert "witness" in (exc.details or {})


def test_v2_merge_commutative_succeeds():
    server = OplogServer()
    sid = _new_session(server)

    left = server.create_branch(sid, from_branch="main", from_seq=0, name="left-c")
    right = server.create_branch(sid, from_branch="main", from_seq=0, name="right-c")

    server.append_op(
        sid=sid,
        branch_id=left["branch_id"],
        spec=OperationSpec(
            op_id="left-elim",
            op_type="retract",
            payload={"eliminate": ["H1"]},
            source_id="test",
        ),
    )
    server.append_op(
        sid=sid,
        branch_id=right["branch_id"],
        spec=OperationSpec(
            op_id="right-elim",
            op_type="retract",
            payload={"eliminate": ["H2"]},
            source_id="test",
        ),
    )

    merged = server.merge(
        sid=sid,
        base_branch="main",
        base_seq=0,
        heads=[
            {"branch": left["branch_id"], "seq": 1},
            {"branch": right["branch_id"], "seq": 1},
        ],
        policy="refuse_non_commutative",
        reducer="v1_mask_meet_tombstone",
    )

    assert merged["merged_branch_id"]
    assert len(merged["merge_plan"]) == 2


def test_v2_analysis_replay_across_reducer_versions():
    server = OplogServer()
    sid = _new_session(server)

    server.append_op(
        sid=sid,
        branch_id="main",
        spec=OperationSpec(
            op_id="set-root",
            op_type="assert",
            payload={"set": {"root": "db"}},
            source_id="test",
        ),
    )
    server.append_op(
        sid=sid,
        branch_id="main",
        spec=OperationSpec(
            op_id="conditional-elim",
            op_type="refine",
            payload={"if_attr": "root", "equals": "db", "eliminate": ["H2"]},
            source_id="test",
        ),
    )

    replay = server.analyze_replay(
        sid=sid,
        branch="main",
        from_seq=1,
        to_seq=2,
        reducers=["v1_mask_meet_tombstone", "v1_mask_no_refine"],
    )

    assert len(replay["results"]) == 2
    assert replay["results"][0]["state_hash"] != replay["results"][1]["state_hash"]
    assert replay["results"][1]["delta_vs_baseline"]["changed"] is True
