"""SPI surface for CMBS adapters."""

from .adapter import discover_providers
from .hypothesis_provider import HypothesisProvider

__all__ = [
    "HypothesisProvider",
    "discover_providers",
]
