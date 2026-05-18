"""
Twenty Questions reference kit loader.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path


@dataclass(frozen=True)
class ActionSpec:
    action_id: str
    question: str
    keep: dict[str, list[str]]


@dataclass(frozen=True)
class TwentyQKit:
    hypotheses: list[str]
    actions: dict[str, ActionSpec]
    actions_order: list[str]


def load_kit(path: str | Path) -> TwentyQKit:
    """Load a kit from a filesystem path."""
    return _kit_from_text(Path(path).read_text())


def load_builtin_kit(name: str) -> TwentyQKit:
    """Load one of the kits shipped with the package, e.g. ``"20q_4"``."""
    resource = resources.files(__package__).joinpath("kits", f"{name}.yaml")
    return _kit_from_text(resource.read_text())


def _kit_from_text(text: str) -> TwentyQKit:
    data = _parse_yaml(text)
    hypotheses = list(data.get("hypotheses", []))
    actions_raw = list(data.get("actions", []))
    actions: dict[str, ActionSpec] = {}
    order: list[str] = []
    for item in actions_raw:
        action_id = item["id"]
        question = item["question"]
        keep = item["keep"]
        actions[action_id] = ActionSpec(action_id=action_id, question=question, keep=keep)
        order.append(action_id)
    return TwentyQKit(hypotheses=hypotheses, actions=actions, actions_order=order)


def _parse_yaml(text: str) -> dict:
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on optional dep
        raise RuntimeError(
            "pyyaml is required to load kit files. Install with `pip install pyyaml`."
        ) from exc
    return yaml.safe_load(text)
