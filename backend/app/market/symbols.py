"""The markets the lab can chart, and which free data provider supplies each."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Symbol:
    code: str  # our code, also used in URLs
    name: str
    asset_class: str  # forex | metal | commodity | stock | etf
    provider: str  # oanda | twelvedata
    provider_symbol: str
    precision: int  # decimal places to show
    base_price: float  # starting point for clearly-labelled sample data only

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("base_price")
        return d


def _fx(code: str, name: str, precision: int, base: float) -> Symbol:
    return Symbol(code, name, "forex", "oanda", code, precision, base)


SYMBOLS: dict[str, Symbol] = {
    s.code: s
    for s in [
        # Forex (OANDA demo feed)
        _fx("EUR_USD", "Euro / US Dollar", 5, 1.08),
        _fx("GBP_USD", "British Pound / US Dollar", 5, 1.27),
        _fx("USD_JPY", "US Dollar / Japanese Yen", 3, 150.0),
        _fx("USD_CHF", "US Dollar / Swiss Franc", 5, 0.89),
        _fx("AUD_USD", "Australian Dollar / US Dollar", 5, 0.66),
        _fx("USD_CAD", "US Dollar / Canadian Dollar", 5, 1.36),
        _fx("NZD_USD", "New Zealand Dollar / US Dollar", 5, 0.61),
        _fx("EUR_GBP", "Euro / British Pound", 5, 0.85),
        _fx("EUR_JPY", "Euro / Japanese Yen", 3, 162.0),
        _fx("GBP_JPY", "British Pound / Japanese Yen", 3, 190.0),
        # Metals and commodities (OANDA demo feed)
        Symbol("XAU_USD", "Gold", "metal", "oanda", "XAU_USD", 2, 2300.0),
        Symbol("XAG_USD", "Silver", "metal", "oanda", "XAG_USD", 3, 28.0),
        Symbol("BCO_USD", "Brent Crude Oil", "commodity", "oanda", "BCO_USD", 2, 80.0),
        Symbol("WTICO_USD", "West Texas Oil", "commodity", "oanda", "WTICO_USD", 2, 76.0),
        Symbol("NATGAS_USD", "Natural Gas", "commodity", "oanda", "NATGAS_USD", 3, 2.5),
        Symbol("XCU_USD", "Copper", "commodity", "oanda", "XCU_USD", 4, 4.3),
        Symbol("CORN_USD", "Corn", "commodity", "oanda", "CORN_USD", 3, 4.5),
        Symbol("WHEAT_USD", "Wheat", "commodity", "oanda", "WHEAT_USD", 3, 5.8),
        Symbol("SUGAR_USD", "Sugar", "commodity", "oanda", "SUGAR_USD", 4, 0.2),
        # US stocks and ETFs (Twelve Data free plan)
        Symbol("AAPL", "Apple", "stock", "twelvedata", "AAPL", 2, 190.0),
        Symbol("MSFT", "Microsoft", "stock", "twelvedata", "MSFT", 2, 420.0),
        Symbol("NVDA", "NVIDIA", "stock", "twelvedata", "NVDA", 2, 120.0),
        Symbol("AMZN", "Amazon", "stock", "twelvedata", "AMZN", 2, 180.0),
        Symbol("GOOGL", "Alphabet", "stock", "twelvedata", "GOOGL", 2, 170.0),
        Symbol("META", "Meta Platforms", "stock", "twelvedata", "META", 2, 500.0),
        Symbol("TSLA", "Tesla", "stock", "twelvedata", "TSLA", 2, 200.0),
        Symbol("JPM", "JPMorgan Chase", "stock", "twelvedata", "JPM", 2, 200.0),
        Symbol("KO", "Coca-Cola", "stock", "twelvedata", "KO", 2, 62.0),
        Symbol("JNJ", "Johnson & Johnson", "stock", "twelvedata", "JNJ", 2, 155.0),
        Symbol("SPY", "S&P 500 ETF", "etf", "twelvedata", "SPY", 2, 520.0),
        Symbol("QQQ", "Nasdaq-100 ETF", "etf", "twelvedata", "QQQ", 2, 440.0),
        Symbol("VTI", "Total US Market ETF", "etf", "twelvedata", "VTI", 2, 260.0),
    ]
}


def get_symbol(code: str) -> Symbol:
    try:
        return SYMBOLS[code]
    except KeyError as exc:
        raise ValueError(f"Unknown symbol '{code}'.") from exc
