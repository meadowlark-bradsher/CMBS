"""Reducer registry for CMBS v2 transcript-conditioned state derivation."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .op_models import OperationEnvelope


class Reducer(Protocol):
    def reduce(
        self,
        initial_hypotheses: Iterable[str],
        accepted_ops: Iterable[OperationEnvelope],
    ) -> dict[str, Any]:
        """Reduce accepted operations into a state projection."""


@dataclass(frozen=True)
class ReduceResult:
    reducer_version: str
    state_projection: dict[str, Any]


class V1MaskMeetTombstoneReducer:
    """Baseline set-based reducer with explicit order sensitivity for refinement."""

    version = "v1_mask_meet_tombstone"

    def reduce(
        self,
        initial_hypotheses: Iterable[str],
        accepted_ops: Iterable[OperationEnvelope],
    ) -> dict[str, Any]:
        survivors = set(initial_hypotheses)
        eliminated = set()
        attrs: dict[str, Any] = {}

        for op in accepted_ops:
            payload = op.payload or {}
            op_type = op.op_type

            if op_type in {"retract", "tombstone"}:
                to_eliminate = set(_list(payload.get("eliminate")))
                newly = to_eliminate & survivors
                survivors -= newly
                eliminated |= newly
                continue

            if op_type in {"assert", "oracle_answer"}:
                to_eliminate = set(_list(payload.get("eliminate")))
                newly = to_eliminate & survivors
                survivors -= newly
                eliminated |= newly
                set_fields = payload.get("set")
                if isinstance(set_fields, Mapping):
                    for k, v in set_fields.items():
                        attrs[str(k)] = v
                continue

            if op_type == "refine":
                key = payload.get("if_attr")
                expected = payload.get("equals")
                to_eliminate = set(_list(payload.get("eliminate")))
                if key is None:
                    continue
                if attrs.get(str(key)) == expected:
                    newly = to_eliminate & survivors
                    survivors -= newly
                    eliminated |= newly
                continue

            # branch_note and unknown op types are no-ops for this reducer.

        return {
            "survivors": sorted(survivors),
            "eliminated": sorted(eliminated),
            "attrs": _canonicalize(attrs),
            "n_survivors": len(survivors),
        }


class V1MaskNoRefineReducer:
    """Variant reducer used for replay/version comparison tests."""

    version = "v1_mask_no_refine"

    def reduce(
        self,
        initial_hypotheses: Iterable[str],
        accepted_ops: Iterable[OperationEnvelope],
    ) -> dict[str, Any]:
        survivors = set(initial_hypotheses)
        eliminated = set()
        attrs: dict[str, Any] = {}

        for op in accepted_ops:
            payload = op.payload or {}
            op_type = op.op_type

            if op_type in {"retract", "tombstone", "assert", "oracle_answer"}:
                to_eliminate = set(_list(payload.get("eliminate")))
                newly = to_eliminate & survivors
                survivors -= newly
                eliminated |= newly
                set_fields = payload.get("set")
                if isinstance(set_fields, Mapping):
                    for k, v in set_fields.items():
                        attrs[str(k)] = v
                continue

            # refine is intentionally ignored in this reducer version.

        return {
            "survivors": sorted(survivors),
            "eliminated": sorted(eliminated),
            "attrs": _canonicalize(attrs),
            "n_survivors": len(survivors),
        }


def default_reducer_registry() -> dict[str, Reducer]:
    reducer_v1 = V1MaskMeetTombstoneReducer()
    reducer_no_refine = V1MaskNoRefineReducer()
    return {
        reducer_v1.version: reducer_v1,
        reducer_no_refine.version: reducer_no_refine,
    }


def summarize_projection(projection: dict[str, Any]) -> dict[str, Any]:
    survivors = projection.get("survivors", [])
    eliminated = projection.get("eliminated", [])
    attrs = projection.get("attrs", {})
    return {
        "n_survivors": len(survivors),
        "n_eliminated": len(eliminated),
        "attr_keys": sorted(list(attrs.keys())) if isinstance(attrs, dict) else [],
    }


def projection_diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(set(a.keys()) | set(b.keys()))
    changes = []
    for key in keys:
        if a.get(key) != b.get(key):
            changes.append(
                {
                    "field": key,
                    "left": _canonicalize(a.get(key)),
                    "right": _canonicalize(b.get(key)),
                }
            )
    return {
        "changed": bool(changes),
        "changed_fields": [c["field"] for c in changes],
        "changes": changes,
    }


def canonical_json(value: Any) -> str:
    return json.dumps(_canonicalize(value), sort_keys=True, separators=(",", ":"))


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _canonicalize(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, list):
        return [_canonicalize(v) for v in value]
    if isinstance(value, set):
        return sorted(_canonicalize(v) for v in value)
    return value


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]
