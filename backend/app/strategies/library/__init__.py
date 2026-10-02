"""The strategy library."""

from ..base import Strategy
from .benchmark import BUY_HOLD
from .reversal import BOLLINGER_BOUNCE, RSI_REVERSAL, SUPPORT_RESISTANCE
from .scalping import LONDON_BREAKOUT, RANGE_FADE, SCALP_PULLBACK
from .trend import BREAKOUT, ICHIMOKU_TREND, MA_CROSS, MACD_MOMENTUM, TREND_PULLBACK

STRATEGIES: dict[str, Strategy] = {
    s.key: s
    for s in [
        BUY_HOLD, MA_CROSS, TREND_PULLBACK, RSI_REVERSAL, BOLLINGER_BOUNCE,
        BREAKOUT, MACD_MOMENTUM, ICHIMOKU_TREND, SUPPORT_RESISTANCE,
        LONDON_BREAKOUT, SCALP_PULLBACK, RANGE_FADE,
    ]
}


def get_strategy(key: str) -> Strategy:
    try:
        return STRATEGIES[key]
    except KeyError as exc:
        raise ValueError(f"Unknown strategy '{key}'.") from exc
