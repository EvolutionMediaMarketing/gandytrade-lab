# GandyTrade Lab

A private, single-user trading lab for learning: charts, indicators, and (in later
phases) backtesting, paper trading with pretend money, and coaching. Paper first;
real-money trading is an optional, locked-down later phase.

**Status: phase 1.** Sign-in with two-factor authentication, a private site
gate, and charts for forex, metals, commodities and US stocks with five chart
styles and ten indicators, including the Ichimoku Cloud.

## Safety by design

- No code anywhere in this repository can place an order with a broker. A test
  (`backend/tests/test_safety.py`) fails the build if broker order endpoints or
  live trading hosts appear outside a future, separate live gateway.
- Market data is read-only. The OANDA feed is fixed to the demo (practice) host.
- Without data keys, the app shows clearly labelled sample data.
- The site is private: a password gate, then the app's own login with a
  6-digit authenticator code. It is hidden from search engines.

## Layout

| Folder | What's in it |
| --- | --- |
| `backend/` | Python API (FastAPI): sign-in, market data, indicators, tests |
| `frontend/` | Web interface (React + TradingView Lightweight Charts) |
| `deploy/` | Container build, service definitions, Apache settings, setup scripts |
| `docs/DEPLOY.md` | Step-by-step guide for putting it on the cPanel server |

## Running the tests

```bash
cd backend && pip install -r requirements-dev.txt && python -m pytest -q
cd frontend && npm ci && npm run build
```

Educational use only. Not financial advice. Charts by
[TradingView](https://www.tradingview.com/) Lightweight Charts™.
