"""CMBS v2 operator-log server with transcript-conditioned state semantics."""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from .op_models import BranchRecord, OperationEnvelope, OperationSpec, SessionRecord
from .reducers import (
    Reducer,
    canonical_json,
    default_reducer_registry,
    projection_diff,
    summarize_projection,
)


@dataclass
class OpAppendResult:
    op_id: str
    seq: int
    accepted: bool
    rejected_reason: str | None
    state_hash_after: str
    branch_head_seq: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "op_id": self.op_id,
            "seq": self.seq,
            "accepted": self.accepted,
            "rejected_reason": self.rejected_reason,
            "state_hash_after": self.state_hash_after,
            "branch_head_seq": self.branch_head_seq,
        }


class OplogServerError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        status_code: int = 400,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.status_code = status_code


class OplogServer:
    def __init__(self, reducers: dict[str, Reducer] | None = None) -> None:
        self._reducers = reducers or default_reducer_registry()
        self._sessions: dict[str, SessionRecord] = {}

    def create_session(
        self,
        ontology: dict[str, Any],
        initial_hypotheses: list[str],
        default_reducer: str = "v1_mask_meet_tombstone",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_reducer(default_reducer)
        sid = str(uuid.uuid4())
        now = time.time()
        main = BranchRecord(
            branch_id="main",
            from_branch=None,
            from_seq=0,
            note="main branch",
            created_at=now,
        )
        session = SessionRecord(
            sid=sid,
            ontology=dict(ontology or {}),
            initial_hypotheses=list(initial_hypotheses or []),
            default_reducer=default_reducer,
            metadata=dict(metadata or {}),
            created_at=now,
            branches={"main": main},
        )
        self._sessions[sid] = session
        return {
            "sid": sid,
            "main_branch_id": "main",
            "head_seq": 0,
            "created_at": now,
        }

    def append_op(
        self,
        sid: str,
        branch_id: str,
        spec: OperationSpec,
    ) -> OpAppendResult:
        session = self._get_session(sid)
        branch = self._get_branch(session, branch_id)

        if spec.idempotency_key and spec.idempotency_key in branch.idempotency_index:
            existing = branch.idempotency_index[spec.idempotency_key]
            state = self.get_state(
                sid=sid,
                branch=branch_id,
                at=existing.seq,
                reducer=session.default_reducer,
            )
            return OpAppendResult(
                op_id=existing.op_id,
                seq=existing.seq,
                accepted=existing.accepted,
                rejected_reason=existing.rejected_reason,
                state_hash_after=state["state_hash"],
                branch_head_seq=branch.head_seq,
            )

        if spec.op_id:
            for existing in branch.op_log:
                if existing.op_id == spec.op_id:
                    state = self.get_state(
                        sid=sid,
                        branch=branch_id,
                        at=existing.seq,
                        reducer=session.default_reducer,
                    )
                    return OpAppendResult(
                        op_id=existing.op_id,
                        seq=existing.seq,
                        accepted=existing.accepted,
                        rejected_reason=existing.rejected_reason,
                        state_hash_after=state["state_hash"],
                        branch_head_seq=branch.head_seq,
                    )

        reducer_version = session.default_reducer
        current = self._state_from_log(session, branch, branch.head_seq, reducer_version)
        accepted, rejected_reason = self._check_preconditions(spec.preconditions, current)

        seq = branch.head_seq + 1
        op_id = spec.op_id or str(uuid.uuid4())
        envelope = OperationEnvelope(
            op_id=op_id,
            seq=seq,
            branch_id=branch_id,
            origin_seq=seq,
            op_type=spec.op_type,
            payload=dict(spec.payload or {}),
            source_id=spec.source_id,
            preconditions=list(spec.preconditions),
            commutativity_key=spec.commutativity_key,
            idempotency_key=spec.idempotency_key,
            accepted=accepted,
            rejected_reason=rejected_reason,
            created_at=time.time(),
        )
        branch.op_log.append(envelope)
        if spec.idempotency_key:
            branch.idempotency_index[spec.idempotency_key] = envelope

        state_after = self.get_state(
            sid=sid,
            branch=branch_id,
            at=seq,
            reducer=reducer_version,
        )
        return OpAppendResult(
            op_id=op_id,
            seq=seq,
            accepted=accepted,
            rejected_reason=rejected_reason,
            state_hash_after=state_after["state_hash"],
            branch_head_seq=branch.head_seq,
        )

    def create_branch(
        self,
        sid: str,
        from_branch: str,
        from_seq: int,
        name: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        session = self._get_session(sid)
        source = self._get_branch(session, from_branch)
        if from_seq < 0 or from_seq > source.head_seq:
            raise OplogServerError(
                code="INVALID_SEQ",
                message="from_seq out of range for source branch.",
                details={"from_seq": from_seq, "head_seq": source.head_seq},
                status_code=400,
            )

        branch_id = self._unique_branch_id(session, name)
        now = time.time()
        copied = list(source.op_log[:from_seq])
        idem: dict[str, OperationEnvelope] = {}
        for env in copied:
            if env.idempotency_key:
                idem[env.idempotency_key] = env

        branch = BranchRecord(
            branch_id=branch_id,
            from_branch=from_branch,
            from_seq=from_seq,
            note=note,
            created_at=now,
            op_log=copied,
            idempotency_index=idem,
        )
        session.branches[branch_id] = branch
        return {
            "branch_id": branch_id,
            "from_branch": from_branch,
            "from_seq": from_seq,
            "head_seq": branch.head_seq,
        }

    def get_ops(
        self,
        sid: str,
        branch: str,
        from_seq: int | None = None,
        to_seq: int | None = None,
    ) -> dict[str, Any]:
        session = self._get_session(sid)
        branch_rec = self._get_branch(session, branch)

        if branch_rec.head_seq == 0:
            return {"sid": sid, "branch": branch, "from": 0, "to": 0, "ops": []}

        start = from_seq if from_seq is not None else 1
        end = to_seq if to_seq is not None else branch_rec.head_seq
        if start < 1 or end < 0 or start > branch_rec.head_seq:
            raise OplogServerError(
                code="INVALID_SEQ",
                message="from/to sequence out of range.",
                details={"from": start, "to": end, "head_seq": branch_rec.head_seq},
                status_code=400,
            )
        if end > branch_rec.head_seq:
            raise OplogServerError(
                code="INVALID_SEQ",
                message="to sequence out of range.",
                details={"to": end, "head_seq": branch_rec.head_seq},
                status_code=400,
            )
        if start > end:
            return {"sid": sid, "branch": branch, "from": start, "to": end, "ops": []}

        ops = [env.to_dict() for env in branch_rec.op_log[start - 1 : end]]
        return {"sid": sid, "branch": branch, "from": start, "to": end, "ops": ops}

    def get_state(
        self,
        sid: str,
        branch: str,
        at: int | None,
        reducer: str | None,
    ) -> dict[str, Any]:
        session = self._get_session(sid)
        branch_rec = self._get_branch(session, branch)
        reducer_version = reducer or session.default_reducer
        self._require_reducer(reducer_version)

        at_seq = branch_rec.head_seq if at is None else at
        if at_seq < 0 or at_seq > branch_rec.head_seq:
            raise OplogServerError(
                code="INVALID_SEQ",
                message="Requested state sequence is out of range.",
                details={"at": at_seq, "head_seq": branch_rec.head_seq},
                status_code=400,
            )

        projection = self._state_from_log(session, branch_rec, at_seq, reducer_version)
        state_hash = self._state_hash(
            sid=sid,
            branch=branch,
            at=at_seq,
            reducer_version=reducer_version,
            projection=projection,
        )
        audit_head = branch_rec.op_log[at_seq - 1].op_id if at_seq > 0 else None
        return {
            "sid": sid,
            "branch": branch,
            "at": at_seq,
            "reducer_version": reducer_version,
            "state_hash": state_hash,
            "state_projection": projection,
            "audit_head": audit_head,
        }

    def analyze_commute(
        self,
        sid: str,
        branch: str,
        seq: int,
        reducer: str,
        op_a: OperationSpec,
        op_b: OperationSpec,
    ) -> dict[str, Any]:
        session = self._get_session(sid)
        branch_rec = self._get_branch(session, branch)
        self._require_reducer(reducer)
        if seq < 0 or seq > branch_rec.head_seq:
            raise OplogServerError(
                code="INVALID_SEQ",
                message="Sequence out of range for commutativity analysis.",
                details={"seq": seq, "head_seq": branch_rec.head_seq},
                status_code=400,
            )

        hash_ab, state_ab = self._simulate_sequence(
            session,
            branch_rec,
            seq,
            reducer,
            [op_a, op_b],
        )
        hash_ba, state_ba = self._simulate_sequence(
            session,
            branch_rec,
            seq,
            reducer,
            [op_b, op_a],
        )

        commutes = hash_ab == hash_ba
        diff = projection_diff(state_ab, state_ba)

        response = {
            "commutes": commutes,
            "state_hash_a_then_b": hash_ab,
            "state_hash_b_then_a": hash_ba,
            "diff_summary": diff,
        }
        if not commutes:
            response["witness"] = {
                "op_a": self._spec_to_dict(op_a),
                "op_b": self._spec_to_dict(op_b),
                "hash_a_then_b": hash_ab,
                "hash_b_then_a": hash_ba,
                "diff_summary": diff,
            }
        return response

    def analyze_replay(
        self,
        sid: str,
        branch: str,
        from_seq: int | None,
        to_seq: int | None,
        reducers: list[str],
    ) -> dict[str, Any]:
        session = self._get_session(sid)
        branch_rec = self._get_branch(session, branch)

        start = from_seq if from_seq is not None else 1
        end = to_seq if to_seq is not None else branch_rec.head_seq
        if end < 0 or start < 1 or start > max(branch_rec.head_seq, 1):
            raise OplogServerError(
                code="INVALID_SEQ",
                message="Replay range is out of bounds.",
                details={"from": start, "to": end, "head_seq": branch_rec.head_seq},
                status_code=400,
            )
        if end > branch_rec.head_seq:
            raise OplogServerError(
                code="INVALID_SEQ",
                message="Replay 'to' out of range.",
                details={"to": end, "head_seq": branch_rec.head_seq},
                status_code=400,
            )
        if start > end:
            return {"sid": sid, "branch": branch, "from": start, "to": end, "results": []}

        if not reducers:
            raise OplogServerError(
                code="INVALID_REQUEST",
                message="At least one reducer must be provided.",
                status_code=400,
            )

        accepted_slice = [env for env in branch_rec.op_log[start - 1 : end] if env.accepted]
        results = []
        baseline_projection: dict[str, Any] | None = None

        for idx, reducer_name in enumerate(reducers):
            self._require_reducer(reducer_name)
            reducer_impl = self._reducers[reducer_name]
            projection = reducer_impl.reduce(session.initial_hypotheses, accepted_slice)
            state_hash = self._state_hash(
                sid=sid,
                branch=branch,
                at=end,
                reducer_version=reducer_name,
                projection=projection,
            )
            if idx == 0:
                baseline_projection = projection
            delta = projection_diff(baseline_projection or {}, projection)
            results.append(
                {
                    "reducer_version": reducer_name,
                    "state_hash": state_hash,
                    "state_projection_summary": summarize_projection(projection),
                    "delta_vs_baseline": delta,
                }
            )

        return {
            "sid": sid,
            "branch": branch,
            "from": start,
            "to": end,
            "results": results,
        }

    def merge(
        self,
        sid: str,
        base_branch: str,
        base_seq: int,
        heads: list[dict[str, Any]],
        policy: str,
        reducer: str,
    ) -> dict[str, Any]:
        session = self._get_session(sid)
        base = self._get_branch(session, base_branch)
        self._require_reducer(reducer)

        if policy != "refuse_non_commutative":
            raise OplogServerError(
                code="INVALID_POLICY",
                message="Only 'refuse_non_commutative' policy is supported in phase 1.",
                details={"policy": policy},
                status_code=400,
            )
        if base_seq < 0 or base_seq > base.head_seq:
            raise OplogServerError(
                code="INVALID_SEQ",
                message="base.seq out of range.",
                details={"base_seq": base_seq, "head_seq": base.head_seq},
                status_code=400,
            )
        if len(heads) < 1:
            raise OplogServerError(
                code="INVALID_REQUEST",
                message="At least one merge head is required.",
                status_code=400,
            )

        resolved_heads: list[tuple[BranchRecord, int]] = []
        for head in heads:
            branch_name = str(head.get("branch", ""))
            seq = int(head.get("seq", -1))
            branch_rec = self._get_branch(session, branch_name)
            if seq < 0 or seq > branch_rec.head_seq:
                raise OplogServerError(
                    code="INVALID_SEQ",
                    message="Head sequence out of range.",
                    details={"branch": branch_name, "seq": seq, "head_seq": branch_rec.head_seq},
                    status_code=400,
                )
            resolved_heads.append((branch_rec, seq))

        for (left, left_seq), (right, right_seq) in combinations(resolved_heads, 2):
            left_tail = [op for op in left.op_log[base_seq:left_seq] if op.accepted]
            right_tail = [op for op in right.op_log[base_seq:right_seq] if op.accepted]
            for op_left in left_tail:
                for op_right in right_tail:
                    commute = self.analyze_commute(
                        sid=sid,
                        branch=base_branch,
                        seq=base_seq,
                        reducer=reducer,
                        op_a=self._spec_from_env(op_left),
                        op_b=self._spec_from_env(op_right),
                    )
                    if not commute["commutes"]:
                        raise OplogServerError(
                            code="NON_COMMUTATIVE_CONFLICT",
                            message="Merge refused: order changes outcome for at least one op pair.",
                            details={"witness": commute.get("witness")},
                            status_code=409,
                        )

        merge_branch = self.create_branch(
            sid=sid,
            from_branch=base_branch,
            from_seq=base_seq,
            name=f"merge_{int(time.time())}",
            note="phase-1 merge",
        )
        merged_branch_id = merge_branch["branch_id"]

        tails: list[OperationEnvelope] = []
        for branch_rec, seq in resolved_heads:
            tails.extend([op for op in branch_rec.op_log[base_seq:seq] if op.accepted])
        tails.sort(key=lambda op: (op.branch_id, op.origin_seq, op.op_id))

        merge_plan = []
        for op in tails:
            result = self.append_op(
                sid=sid,
                branch_id=merged_branch_id,
                spec=OperationSpec(
                    op_id=f"{op.branch_id}:{op.origin_seq}:{op.op_id}",
                    op_type=op.op_type,
                    payload=dict(op.payload),
                    source_id=f"merge:{op.source_id}",
                    preconditions=list(op.preconditions),
                    commutativity_key=op.commutativity_key,
                    idempotency_key=None,
                ),
            )
            merge_plan.append(result.to_dict())

        final = self.get_state(
            sid=sid,
            branch=merged_branch_id,
            at=None,
            reducer=reducer,
        )
        return {
            "merged_branch_id": merged_branch_id,
            "merge_plan": merge_plan,
            "state_hash": final["state_hash"],
        }

    def _state_from_log(
        self,
        session: SessionRecord,
        branch: BranchRecord,
        at_seq: int,
        reducer_version: str,
    ) -> dict[str, Any]:
        self._require_reducer(reducer_version)
        reducer = self._reducers[reducer_version]
        accepted = [op for op in branch.op_log[:at_seq] if op.accepted]
        return reducer.reduce(session.initial_hypotheses, accepted)

    def _simulate_sequence(
        self,
        session: SessionRecord,
        branch: BranchRecord,
        base_seq: int,
        reducer_version: str,
        ops: list[OperationSpec],
    ) -> tuple[str, dict[str, Any]]:
        temp_log = list(branch.op_log[:base_seq])
        seq = base_seq
        for idx, spec in enumerate(ops, start=1):
            current = self._reducers[reducer_version].reduce(
                session.initial_hypotheses,
                [op for op in temp_log if op.accepted],
            )
            accepted, reason = self._check_preconditions(spec.preconditions, current)
            seq += 1
            temp_log.append(
                OperationEnvelope(
                    op_id=spec.op_id or f"sim-{idx}-{uuid.uuid4().hex[:8]}",
                    seq=seq,
                    branch_id=branch.branch_id,
                    origin_seq=seq,
                    op_type=spec.op_type,
                    payload=dict(spec.payload),
                    source_id=spec.source_id,
                    preconditions=list(spec.preconditions),
                    commutativity_key=spec.commutativity_key,
                    idempotency_key=spec.idempotency_key,
                    accepted=accepted,
                    rejected_reason=reason,
                    created_at=0.0,
                )
            )

        projection = self._reducers[reducer_version].reduce(
            session.initial_hypotheses,
            [op for op in temp_log if op.accepted],
        )
        state_hash = self._state_hash(
            sid=session.sid,
            branch=branch.branch_id,
            at=seq,
            reducer_version=reducer_version,
            projection=projection,
        )
        return state_hash, projection

    def _check_preconditions(
        self,
        preconditions: Iterable[str],
        state_projection: dict[str, Any],
    ) -> tuple[bool, str | None]:
        survivors = set(state_projection.get("survivors", []))
        eliminated = set(state_projection.get("eliminated", []))
        attrs = state_projection.get("attrs", {})
        if not isinstance(attrs, dict):
            attrs = {}

        for raw in preconditions:
            if not isinstance(raw, str):
                return False, "invalid precondition type"
            if raw.startswith("survivors_contains:"):
                hid = raw.split(":", 1)[1]
                if hid not in survivors:
                    return False, f"precondition failed: {raw}"
                continue
            if raw.startswith("survivors_not_contains:"):
                hid = raw.split(":", 1)[1]
                if hid in survivors:
                    return False, f"precondition failed: {raw}"
                continue
            if raw.startswith("eliminated_contains:"):
                hid = raw.split(":", 1)[1]
                if hid not in eliminated:
                    return False, f"precondition failed: {raw}"
                continue
            if raw.startswith("eliminated_not_contains:"):
                hid = raw.split(":", 1)[1]
                if hid in eliminated:
                    return False, f"precondition failed: {raw}"
                continue
            if raw.startswith("attrs_eq:"):
                token = raw.split(":", 1)[1]
                if "=" not in token:
                    return False, f"invalid precondition: {raw}"
                key, expected = token.split("=", 1)
                if str(attrs.get(key)) != expected:
                    return False, f"precondition failed: {raw}"
                continue
            if raw.startswith("attrs_ne:"):
                token = raw.split(":", 1)[1]
                if "=" not in token:
                    return False, f"invalid precondition: {raw}"
                key, expected = token.split("=", 1)
                if str(attrs.get(key)) == expected:
                    return False, f"precondition failed: {raw}"
                continue
            return False, f"unsupported precondition: {raw}"

        return True, None

    def _state_hash(
        self,
        sid: str,
        branch: str,
        at: int,
        reducer_version: str,
        projection: dict[str, Any],
    ) -> str:
        payload = (
            canonical_json(projection)
            + "|"
            + reducer_version
            + "|"
            + sid
            + "|"
            + branch
            + "|"
            + str(at)
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _get_session(self, sid: str) -> SessionRecord:
        session = self._sessions.get(sid)
        if session is None:
            raise OplogServerError(
                code="SESSION_NOT_FOUND",
                message="Session not found.",
                details={"sid": sid},
                status_code=404,
            )
        return session

    def _get_branch(self, session: SessionRecord, branch_id: str) -> BranchRecord:
        branch = session.branches.get(branch_id)
        if branch is None:
            raise OplogServerError(
                code="BRANCH_NOT_FOUND",
                message="Branch not found.",
                details={"sid": session.sid, "branch": branch_id},
                status_code=404,
            )
        return branch

    def _require_reducer(self, reducer_name: str) -> None:
        if reducer_name not in self._reducers:
            raise OplogServerError(
                code="REDUCER_NOT_FOUND",
                message="Unknown reducer.",
                details={"reducer": reducer_name},
                status_code=400,
            )

    def _unique_branch_id(self, session: SessionRecord, name: str) -> str:
        base = _slugify(name) or f"b{len(session.branches) + 1}"
        branch_id = base
        idx = 2
        while branch_id in session.branches:
            branch_id = f"{base}_{idx}"
            idx += 1
        return branch_id

    @staticmethod
    def _spec_from_env(env: OperationEnvelope) -> OperationSpec:
        return OperationSpec(
            op_id=env.op_id,
            op_type=env.op_type,
            payload=dict(env.payload),
            source_id=env.source_id,
            preconditions=list(env.preconditions),
            commutativity_key=env.commutativity_key,
            idempotency_key=env.idempotency_key,
        )

    @staticmethod
    def _spec_to_dict(spec: OperationSpec) -> dict[str, Any]:
        return {
            "op_id": spec.op_id,
            "type": spec.op_type,
            "payload": spec.payload,
            "source_id": spec.source_id,
            "preconditions": list(spec.preconditions),
            "commutativity_key": spec.commutativity_key,
            "idempotency_key": spec.idempotency_key,
        }


def _slugify(value: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
    s = re.sub(r"_+", "_", s)
    return s.strip("_")
