"""
ITBench reference kit loader.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path


@dataclass(frozen=True)
class ActionSpec:
    action_id: str
    description: str
    outcomes: list[str]


@dataclass(frozen=True)
class ITBenchKit:
    hypotheses: list[str]
    actions: dict[str, ActionSpec]
    actions_order: list[str]
    oracle_table: dict[str, dict[str, dict[str, list[str]]]]


def load_kit(path: str | Path) -> ITBenchKit:
    """Load a kit from a filesystem path."""
    return _kit_from_text(Path(path).read_text())


def load_builtin_kit(name: str) -> ITBenchKit:
    """Load one of the kits shipped with the package, e.g. ``"itb_min_4"``."""
    resource = resources.files(__package__).joinpath("kits", f"{name}.yaml")
    return _kit_from_text(resource.read_text())


def _kit_from_text(text: str) -> ITBenchKit:
    data = _parse_yaml(text)
    hypotheses = list(data.get("hypotheses", []))
    actions_raw = list(data.get("actions", []))
    oracle_table = data.get("oracle_table", {})
    actions: dict[str, ActionSpec] = {}
    order: list[str] = []
    for item in actions_raw:
        action_id = item["id"]
        description = item["description"]
        outcomes = list(item["outcomes"])
        actions[action_id] = ActionSpec(
            action_id=action_id,
            description=description,
            outcomes=outcomes,
        )
        order.append(action_id)
    return ITBenchKit(
        hypotheses=hypotheses,
        actions=actions,
        actions_order=order,
        oracle_table=oracle_table,
    )


def _parse_yaml(text: str) -> dict:
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on optional dep
        raise RuntimeError(
            "pyyaml is required to load kit files. Install with `pip install pyyaml`."
        ) from exc
    return yaml.safe_load(text)
