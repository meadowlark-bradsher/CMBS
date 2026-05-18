"""
SPI interface for hypothesis providers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol


class HypothesisProvider(Protocol):
    """
    SPI interface implemented by domain adapters.
    CMBS treats this as opaque.
    """

    # ---- identity ----
    def id(self) -> str: ...

    def version(self) -> str: ...

    # ---- hypothesis space ----
    def hypothesis_ids(self) -> Iterable[str]: ...

    # ---- probe interface ----
    def probe_ids(self) -> Iterable[str]: ...

    def apply_probe(self, probe_id: str, response: Any) -> Mapping[str, bool]:
        """
        Returns elimination mask:
        hypothesis_id -> eliminated?
        """
