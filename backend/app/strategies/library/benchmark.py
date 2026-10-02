"""Buy and hold: the yardstick every other strategy has to beat."""

import pandas as pd

from ..base import Rules, Side, Strategy, never


def _buy_hold(df: pd.DataFrame, p: dict) -> Rules:
    first = pd.Series(False, index=df.index)
    if len(first):
        first.iloc[0] = True
    long = Side(
        conditions={"Buy on the first candle and keep it": first},
        exit=never(df.index),
        stop=pd.Series(0.0, index=df.index),
        exit_label="Never sells until the end of the test",
        stop_label="No stop-loss",
    )
    return Rules(long, None)


BUY_HOLD = Strategy(
    key="buy_hold",
    name="Buy and hold",
    summary="Buy at the start and keep it. The yardstick: a strategy should beat this to be worth the effort.",
    rules_text=[
        "Put the whole balance in at the first candle, with no leverage.",
        "Never sell until the end of the test.",
        "No stop-loss, so this one isn't limited by the risk guard. It's shown as a comparison.",
    ],
    works_when="Markets that rise over the long run, such as broad share indices.",
    fails_when="Long bear markets; currencies, which don't tend to rise over time.",
    exercise="Check how deep the worst fall (drawdown) was. Could you have sat through it?",
    params=[],
    compute=_buy_hold,
    benchmark=True,
    can_short=False,
)
