"""Synthetic data generator + loader (stands in for the connector layer)."""

from .generator import generate
from .loader import RunSummary, load

__all__ = ["generate", "load", "RunSummary"]
