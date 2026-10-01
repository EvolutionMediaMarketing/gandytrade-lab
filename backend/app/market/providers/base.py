"""Common types for read-only price providers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Bar:
    ts: int  # bar open time, Unix seconds UTC
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class ProviderError(Exception):
    """A provider couldn't supply data; the message is shown to the user."""
