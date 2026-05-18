"""
SPI discovery for hypothesis providers.
"""

from __future__ import annotations

from importlib import metadata

from .hypothesis_provider import HypothesisProvider


def discover_providers() -> dict[str, type[HypothesisProvider]]:
    try:
        eps = metadata.entry_points()
    except Exception:
        return {}

    if hasattr(eps, "select"):
        group = eps.select(group="cmbs.hypotheses")
    else:
        group = eps.get("cmbs.hypotheses", [])

    return {ep.name: ep.load() for ep in group}
