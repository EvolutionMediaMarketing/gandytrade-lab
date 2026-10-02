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
    # Gap between the buy (ask) and sell (bid) price, in price units, where the provider records it:
    # the wider of the two at the candle's open and close. None means use the typical spread.
    spread: float | None = None


class ProviderError(Exception):
    """A provider couldn't supply data; the message is shown to the user."""
