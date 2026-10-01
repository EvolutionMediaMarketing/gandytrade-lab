"""Chart timeframes and how each provider names them."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Timeframe:
    code: str
    label: str
    seconds: int
    oanda: str
    twelvedata: str
    intraday: bool


TIMEFRAMES: dict[str, Timeframe] = {
    tf.code: tf
    for tf in [
        Timeframe("1m", "1 minute", 60, "M1", "1min", True),
        Timeframe("5m", "5 minutes", 300, "M5", "5min", True),
        Timeframe("15m", "15 minutes", 900, "M15", "15min", True),
        Timeframe("30m", "30 minutes", 1800, "M30", "30min", True),
        Timeframe("1h", "1 hour", 3600, "H1", "1h", True),
        Timeframe("4h", "4 hours", 14400, "H4", "4h", True),
        Timeframe("1d", "Daily", 86400, "D", "1day", False),
        Timeframe("1w", "Weekly", 604800, "W", "1week", False),
        Timeframe("1M", "Monthly", 2592000, "M", "1month", False),
    ]
}


def get_timeframe(code: str) -> Timeframe:
    try:
        return TIMEFRAMES[code]
    except KeyError as exc:
        raise ValueError(f"Unknown timeframe '{code}'.") from exc


def refresh_after_seconds(tf: Timeframe) -> int:
    """How long cached bars stay fresh before asking the provider again."""
    if tf.seconds <= 300:
        return 60
    if tf.seconds <= 3600:
        return 300
    if tf.intraday:
        return 900
    return 3600
