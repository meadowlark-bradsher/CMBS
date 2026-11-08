"""
The chained per-envelope ``log_hash`` (scheme ``log_hash_v1``).

INV-H1 (tamper evidence): editing any field of any envelope changes that
envelope's hash and every later one, and ``Session.recover`` refuses the
altered log.

INV-H2 (replay determinism): recomputing the chain from the persisted
envelopes reproduces it exactly, ``created_at`` included; the chain is
independent of ``state_hash``, which covers the reducer's projection only.

Legacy logs whose envelopes carry ``log_hash = None`` still load; the
leading unhashed run is reported, and verification starts at the first
hashed envelope.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import fields, replace

import pytest

from cmbs import (
    LOG_HASH_GENESIS,
    LOG_HASH_SCHEME,
    InMemoryOpLogStore,
    MaskMeetTombstoneReducer,
    OperationEnvelope,
    OperationSpec,
    RecoveredSession,
    Session,
    canonical_envelope_bytes,
    compute_log_hash,
)

HASHED_FIELDS = (
    "op_id",
    "seq",
    "op_type",
    "payload",
    "source_id",
    "idempotency_key",
    "accepted",
    "rejected_reason",
    "created_at",
)


class _FrozenStore:
    """A read-only ``OpLogStore`` serving a fixed ``RecoveredSession``.

    Lets a test hand ``Session.recover`` any envelope tuple it likes,
    including tampered or legacy ones, without going through the in-memory
    store's append checks.
    """

    def __init__(self, record: RecoveredSession) -> None:
        self._record = record

    def create_session(self, *args, **kwargs):  # pragma: no cover - not used
        raise NotImplementedError

    def append(self, session_id, envelope):  # pragma: no cover - not used
        raise NotImplementedError

    def read_ops(self, session_id, from_seq=None, to_seq=None):
        ops = self._record.envelopes
        lo = 1 if from_seq is None else from_seq
        hi = len(ops) if to_seq is None else to_seq
        return tuple(ops[lo - 1 : hi])

    def head_seq(self, session_id):
        return len(self._record.envelopes)

    def recover(self, session_id):
        return self._record


def _build(store=None, session_id="s") -> Session:
    s = Session(
        hypothesis_ids={"H1", "H2", "H3", "H4"},
        store=store or InMemoryOpLogStore(),
        session_id=session_id,
        stability_window=1,
    )
    s.submit_probe_result("P1", "O1", {"H1"}, source_id="agent-a", provenance={"n": 1})
    s.enter_obligation("OB", min_eliminations=1)
    s.submit_probe_result("P1", "O1", {"H2"})  # rejected, logged
    s.submit_probe_result("P2", "O2", {"H2"}, provenance={"n": 2, "note": "ünïcödé"})
    s.request_obligation_exit("OB")
    s.declare_conclusion("H3")
    return s


def _record_with(session: Session, envelopes) -> RecoveredSession:
    base = session._store.recover(session.session_id)
    return replace(base, envelopes=tuple(envelopes))


def _recompute(envelopes) -> list[str]:
    out, prev = [], None
    for env in envelopes:
        prev = compute_log_hash(prev, env)
        out.append(prev)
    return out


def _tamper(env: OperationEnvelope, field: str) -> OperationEnvelope:
    """Return ``env`` with one field changed to a different, type-compatible value."""
    value = getattr(env, field)
    if field == "payload":
        new = dict(value)
        new["provenance"] = {**new.get("provenance", {}), "edited": True}
    elif field == "seq":
        new = value + 100
    elif field == "created_at":
        new = value + 0.001
    elif field == "accepted":
        new = not value
    elif value is None:
        new = "injected"
    else:
        new = f"{value}-edited"
    return replace(env, **{field: new})


# ----------------------------------------------------------------------
# Scheme definition
# ----------------------------------------------------------------------


class TestScheme:
    def test_first_envelope_chains_from_genesis(self):
        s = _build()
        first = s.operations()[0]
        expected = hashlib.sha256(
            LOG_HASH_GENESIS.encode("utf-8") + canonical_envelope_bytes(first)
        ).hexdigest()
        assert first.log_hash == expected
        assert compute_log_hash(None, first) == expected

    def test_each_link_covers_the_previous_hash(self):
        ops = _build().operations()
        for prev, env in zip(ops, ops[1:], strict=False):
            expected = hashlib.sha256(
                prev.log_hash.encode("utf-8") + canonical_envelope_bytes(env)
            ).hexdigest()
            assert env.log_hash == expected

    def test_canonical_bytes_exclude_the_hash_field(self):
        env = _build().operations()[0]
        assert canonical_envelope_bytes(env) == canonical_envelope_bytes(
            replace(env, log_hash=None)
        )
        assert compute_log_hash(None, env) == compute_log_hash(None, replace(env, log_hash="x"))

    def test_canonical_bytes_are_pinned_json(self):
        env = _build().operations()[3]  # the one with non-ASCII provenance
        text = canonical_envelope_bytes(env).decode("utf-8")
        parsed = json.loads(text)
        assert set(parsed) == set(HASHED_FIELDS)
        assert "log_hash" not in parsed
        assert text == json.dumps(
            parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        assert "ünïcödé" in text  # ensure_ascii=False
        assert " " not in text.replace("ünïcödé", "")  # compact separators

    def test_canonical_form_normalizes_payload_containers(self):
        a = OperationEnvelope(
            op_id="x", seq=1, op_type="t", payload={"b": {2, 1}, "a": (1, 2)}, source_id="",
            idempotency_key=None, accepted=True, rejected_reason=None, created_at=1.0,
        )
        b = replace(a, payload={"a": [1, 2], "b": [1, 2]})
        assert canonical_envelope_bytes(a) == canonical_envelope_bytes(b)

    def test_scheme_identifier_is_stored_and_recovered(self):
        store = InMemoryOpLogStore()
        _build(store)
        assert store.recover("s").log_hash_scheme == LOG_HASH_SCHEME == "log_hash_v1"

    def test_every_envelope_field_is_either_hashed_or_the_hash(self):
        names = {f.name for f in fields(OperationEnvelope)}
        assert names == set(HASHED_FIELDS) | {"log_hash"}


# ----------------------------------------------------------------------
# INV-H1: tamper evidence
# ----------------------------------------------------------------------


class TestTamperEvidence:
    @pytest.mark.parametrize("field", HASHED_FIELDS)
    @pytest.mark.parametrize("index", [0, 2, 5])
    def test_single_field_edit_changes_this_and_every_later_hash(self, field, index):
        ops = list(_build().operations())
        original = _recompute(ops)
        ops[index] = _tamper(ops[index], field)
        edited = _recompute(ops)
        assert edited[:index] == original[:index]
        for i in range(index, len(ops)):
            assert edited[i] != original[i], f"seq {i + 1} unchanged after editing {field}"

    @pytest.mark.parametrize("field", HASHED_FIELDS)
    def test_single_field_edit_makes_recover_raise(self, field):
        s = _build()
        ops = list(s.operations())
        ops[2] = _tamper(ops[2], field)
        store = _FrozenStore(_record_with(s, ops))
        with pytest.raises(ValueError, match="log_hash mismatch at seq"):
            Session.recover(store, "s")

    def test_edit_to_an_early_envelope_is_caught_at_that_envelope(self):
        s = _build()
        ops = list(s.operations())
        ops[0] = _tamper(ops[0], "source_id")
        with pytest.raises(ValueError, match="seq 1"):
            Session.recover(_FrozenStore(_record_with(s, ops)), "s")

    def test_rewriting_the_hash_alone_is_caught(self):
        s = _build()
        ops = list(s.operations())
        ops[4] = replace(ops[4], log_hash="0" * 64)
        with pytest.raises(ValueError, match="seq 5"):
            Session.recover(_FrozenStore(_record_with(s, ops)), "s")

    def test_consistent_suffix_rewrite_passes_the_chain_but_moves_the_head(self):
        """The honest limit of the scheme: whoever can rewrite the log can
        also re-hash every envelope after an edit, and the chain alone
        then verifies. What such a rewrite cannot do is keep the head
        hash, so a head recorded out of band (as tutorial 05 does for
        ``state_hash``) still exposes it."""
        s = _build()
        ops = list(s.operations())
        ops[3] = _tamper(ops[3], "payload")
        prev = ops[2].log_hash
        for i in range(3, len(ops)):
            prev = compute_log_hash(prev, ops[i])
            ops[i] = replace(ops[i], log_hash=prev)
        recovered = Session.recover(_FrozenStore(_record_with(s, ops)), "s")
        assert recovered.head_log_hash != s.head_log_hash

    def test_dropping_an_envelope_is_caught(self):
        s = _build()
        ops = list(s.operations())
        del ops[1]
        with pytest.raises(ValueError, match="log_hash mismatch"):
            Session.recover(_FrozenStore(_record_with(s, ops)), "s")

    def test_hash_missing_after_the_chain_started_is_a_broken_chain(self):
        s = _build()
        ops = list(s.operations())
        ops[3] = replace(ops[3], log_hash=None)
        with pytest.raises(ValueError, match="no log_hash after a hashed envelope"):
            Session.recover(_FrozenStore(_record_with(s, ops)), "s")

    def test_unknown_scheme_is_refused(self):
        s = _build()
        record = replace(s._store.recover("s"), log_hash_scheme="log_hash_v9")
        with pytest.raises(ValueError, match="log_hash_v9"):
            Session.recover(_FrozenStore(record), "s")


# ----------------------------------------------------------------------
# INV-H2: replay determinism, and independence from state_hash
# ----------------------------------------------------------------------


class TestReplayDeterminism:
    def test_recomputing_from_stored_envelopes_reproduces_the_chain(self):
        ops = _build().operations()
        assert _recompute(ops) == [env.log_hash for env in ops]

    def test_recover_reproduces_head_and_reports_nothing_unverified(self):
        store = InMemoryOpLogStore()
        s = _build(store)
        r = Session.recover(store, "s")
        assert r.head_log_hash == s.head_log_hash == s.operations()[-1].log_hash
        assert r.unverified_prefix == 0
        assert [e.log_hash for e in r.operations()] == [e.log_hash for e in s.operations()]

    def test_created_at_is_chained_from_the_record_not_the_clock(self, monkeypatch):
        ops = _build().operations()
        monkeypatch.setattr(time, "time", lambda: 4_000_000_000.0)
        assert _recompute(ops) == [env.log_hash for env in ops]
        # and a different stored created_at is a different chain
        changed = list(ops)
        changed[0] = replace(changed[0], created_at=changed[0].created_at + 1.0)
        assert _recompute(changed)[0] != ops[0].log_hash

    def test_recovered_session_continues_the_chain(self):
        store = InMemoryOpLogStore()
        s = _build(store)
        r = Session.recover(store, "s")
        res = r.submit_probe_result("P3", "O3", {"H3"})
        assert res.accepted
        new = r.operations()[-1]
        assert new.log_hash == compute_log_hash(s.head_log_hash, new)
        assert r.head_log_hash == new.log_hash
        again = Session.recover(store, "s")
        assert again.head_log_hash == new.log_hash

    def test_provenance_edit_moves_log_hash_but_not_state_hash(self):
        s = _build()
        ops = list(s.operations())
        edited = list(ops)
        edited[0] = _tamper(edited[0], "payload")  # provenance only
        assert _recompute(edited)[0] != ops[0].log_hash
        reducer = MaskMeetTombstoneReducer()
        kwargs = dict(session_id="s", stability_window=1)
        before = reducer.reduce(s.initial_hypotheses, ops, **kwargs)
        after = reducer.reduce(s.initial_hypotheses, edited, **kwargs)
        assert before.state_hash == after.state_hash
        assert before.state_hash == s.snapshot().state_hash

    def test_state_hash_and_append_result_are_unchanged_by_the_chain(self):
        """``state_hash`` stays on the snapshot and ``AppendResult``; the
        chain adds nothing there."""
        s = Session(hypothesis_ids={"H1", "H2"}, session_id="s")
        res = s.append(OperationSpec(op_type="probe_result", payload={"eliminate": ["H1"]}))
        assert res.state_hash_after == s.snapshot().state_hash
        assert "log_hash" not in s.snapshot().to_dict()
        assert res.envelope.log_hash is not None

    def test_two_sessions_with_equal_state_have_different_chains(self):
        a = Session(hypothesis_ids={"H1", "H2"}, session_id="same")
        b = Session(hypothesis_ids={"H1", "H2"}, session_id="same")
        a.submit_probe_result("P1", "O1", {"H1"}, provenance={"who": "a"})
        b.submit_probe_result("P1", "O1", {"H1"}, provenance={"who": "b"})
        assert a.snapshot().state_hash == b.snapshot().state_hash
        assert a.head_log_hash != b.head_log_hash

    def test_retry_of_an_op_id_does_not_move_the_head(self):
        s = Session(hypothesis_ids={"H1", "H2"}, session_id="s")
        spec = OperationSpec(op_type="probe_result", payload={"eliminate": ["H1"]}, op_id="op-1")
        first = s.append(spec)
        head = s.head_log_hash
        second = s.append(spec)
        assert second.envelope == first.envelope
        assert s.head_log_hash == head
        assert s.head_seq == 1


# ----------------------------------------------------------------------
# Legacy logs and stores
# ----------------------------------------------------------------------


def _legacy(ops):
    return [replace(env, log_hash=None) for env in ops]


class TestLegacy:
    def test_all_none_log_loads_and_is_reported_unverified(self):
        s = _build()
        ops = _legacy(s.operations())
        r = Session.recover(_FrozenStore(_record_with(s, ops)), "s")
        assert r.unverified_prefix == len(ops)
        assert r.head_log_hash is None
        assert r.snapshot() == s.snapshot()

    def test_legacy_prefix_then_hashed_tail_verifies_the_tail(self):
        s = _build()
        ops = list(s.operations())
        ops[:2] = _legacy(ops[:2])
        prev = None
        for i in range(2, len(ops)):  # the tail chains from genesis
            prev = compute_log_hash(prev, ops[i])
            ops[i] = replace(ops[i], log_hash=prev)
        r = Session.recover(_FrozenStore(_record_with(s, ops)), "s")
        assert r.unverified_prefix == 2
        assert r.head_log_hash == ops[-1].log_hash

    def test_tampered_tail_after_legacy_prefix_is_caught(self):
        s = _build()
        ops = list(s.operations())
        ops[:2] = _legacy(ops[:2])
        prev = None
        for i in range(2, len(ops)):
            prev = compute_log_hash(prev, ops[i])
            ops[i] = replace(ops[i], log_hash=prev)
        ops[4] = _tamper(ops[4], "op_type")
        with pytest.raises(ValueError, match="seq 5"):
            Session.recover(_FrozenStore(_record_with(s, ops)), "s")

    def test_legacy_prefix_edits_are_not_detected(self):
        """What 'unverified' means: the prefix can change without a raise."""
        s = _build()
        ops = _legacy(s.operations())
        ops[1] = _tamper(ops[1], "source_id")
        r = Session.recover(_FrozenStore(_record_with(s, ops)), "s")
        assert r.unverified_prefix == len(ops)

    def test_appending_after_a_legacy_log_starts_a_chain_from_genesis(self):
        store = InMemoryOpLogStore()
        _build(store)
        # Rewrite the in-memory log as legacy, as an old store would hold it.
        log = store._sessions["s"]
        log.envelopes[:] = _legacy(log.envelopes)
        r = Session.recover(store, "s")
        assert r.unverified_prefix == 6
        assert r.submit_probe_result("P3", "O3", {"H3"}).accepted
        new = r.operations()[-1]
        assert new.log_hash == compute_log_hash(None, new)
        again = Session.recover(store, "s")
        assert again.unverified_prefix == 6
        assert again.head_log_hash == new.log_hash

    def test_recovered_session_record_defaults_to_the_current_scheme(self):
        record = RecoveredSession(
            session_id="s",
            initial_hypotheses=frozenset({"H1"}),
            ontology=None,
            stability_window=0,
            reducer_version="v1_mask_meet_tombstone",
            envelopes=(),
        )
        assert record.log_hash_scheme == LOG_HASH_SCHEME
        r = Session.recover(_FrozenStore(record), "s")
        assert r.unverified_prefix == 0 and r.head_log_hash is None

    def test_five_argument_store_still_works_and_envelopes_are_hashed(self):
        """A store written against the original SPI, with no
        ``log_hash_scheme`` parameter, is driven unchanged."""

        class OldStore(InMemoryOpLogStore):
            def create_session(
                self, session_id, initial_hypotheses, ontology, stability_window, reducer_version
            ):
                super().create_session(
                    session_id, initial_hypotheses, ontology, stability_window, reducer_version
                )

        store = OldStore()
        s = _build(store)
        assert all(env.log_hash for env in s.operations())
        r = Session.recover(store, "s")
        assert r.head_log_hash == s.head_log_hash

    def test_in_memory_store_accepts_the_scheme_positionally_and_by_keyword(self):
        store = InMemoryOpLogStore()
        store.create_session("a", frozenset(), None, 0, "v")
        store.create_session("b", frozenset(), None, 0, "v", "custom")
        store.create_session("c", frozenset(), None, 0, "v", log_hash_scheme="other")
        assert store.recover("a").log_hash_scheme == LOG_HASH_SCHEME
        assert store.recover("b").log_hash_scheme == "custom"
        assert store.recover("c").log_hash_scheme == "other"


# ----------------------------------------------------------------------
# Serialization
# ----------------------------------------------------------------------


class TestSerialization:
    def test_to_dict_round_trips_with_log_hash(self):
        for env in _build().operations():
            d = env.to_dict()
            assert d["log_hash"] == env.log_hash
            assert OperationEnvelope(**d) == env
            assert OperationEnvelope(**json.loads(json.dumps(d))) == env

    def test_legacy_dict_without_log_hash_constructs_with_none(self):
        d = _build().operations()[0].to_dict()
        del d["log_hash"]
        env = OperationEnvelope(**d)
        assert env.log_hash is None
        assert env.to_dict()["log_hash"] is None

    def test_hand_built_envelope_defaults_to_no_hash(self):
        env = OperationEnvelope(
            op_id="x", seq=1, op_type="t", payload={}, source_id="",
            idempotency_key=None, accepted=True, rejected_reason=None, created_at=0.0,
        )
        assert env.log_hash is None
