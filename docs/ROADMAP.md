# GandyTrade Lab Roadmap: Phases 2 to 6

1 October 2026

## Overview

Phase 1 is live at gandytrade.co.uk; phases 2 to 5 complete the launch version, and phase 6 adds optional real-money trading only after launch.

**Already built (phase 1):** private password gate, two-factor sign-in, charts for 33 markets in 5 styles and 9 timeframes, 10 indicators including the Ichimoku Cloud, real read-only prices from OANDA demo and Twelve Data free, auto-refresh, and a safety test that blocks any broker order code.

**How the phases ship:** phases 2 to 5 are built in order, each checked at its gate, and released together as the launch version. Phase 6 is built afterwards and unlocks per strategy.

**Rules every phase follows**

- **Paper first.** Nothing places a real trade before phase 6, and the safety test enforces it.
- **Evidence, not advice.** The app shows rule checklists and historical results; it never says "buy now".
- **Same code everywhere.** A strategy is written once and runs unchanged in the backtester, the signal assistant, paper trading and, later, live trading, so results are comparable.
- **Honest results.** Spreads, commission and slippage are always included, and every result is compared with buy-and-hold.
- **Risk guard on every order:** stop-loss required, 1% risk per trade, daily and drawdown limits, leverage capped.
- **No server-wide changes** on the cPanel server; everything stays inside the `gandytradeco` account.
- **Free services** wherever possible, in GBP, for a single private user.
- **Time-light:** designed around about 2 hours a week on hourly and daily charts.

**Stack:** Python 3.12 with FastAPI, SQLAlchemy, PostgreSQL and pandas for all trading logic; TypeScript with React and TradingView Lightweight Charts for the interface; rootless Podman containers on the existing cPanel server.

## At a glance

Phases 2 to 5 ship together at launch; real money comes after.

1. **Phase 2 · Backtesting** (test strategies on history): 9 strategies, backtester with costs, buy-and-hold check; signal assistant, risk guard, position and goal calculators.
   - Gate: a backtest matches a hand-checked spreadsheet.
2. **Phase 3 · Paper trading** (pretend money, live prices): manual and automatic paper trading, monthly top-ups; journal, dashboard, 12-week course, weekly review.
   - Gate: paper accounts run four weeks without errors.
3. **Phase 4 · Practice** (practise and stress-test): market replay and a no-code strategy builder; walk-forward and Monte Carlo checks, alerts, news and events (economic calendar, headlines).
   - Gate: an overfitted test strategy is labelled Reject.
4. **Phase 5 · Graduation** (coach and the bar to clear): optional AI coach chat with a monthly spending cap; graduation checklist and Pine Script export.
   - Gate: phases 2 to 5 pass together.
5. **Before launch** (protect your data): nightly off-server backups with a tested restore; database upgrades, health monitor, security review.
6. **LAUNCH:** phases 2 to 5 released together.
7. **Phase 6 · Live trading** (optional, after launch): real shares first, no leverage, confirm each trade; limits in pounds, broker-held stops, kill switch.
   - Gate before it: a strategy passes the graduation checklist on paper.

Each gate is checked before the next phase builds on it; nothing reaches real money until a strategy has graduated on paper after launch.

## Phase 2: strategies, backtesting and the signal assistant

Phase 2 turns the charts into a test bench: pick a strategy, run it on years of real prices with realistic costs, and see whether it beats simply buying and holding.

| Part | What it does | Where it lives |
| --- | --- | --- |
| Strategy engine | One shared format for strategies (entry, exit, stop-loss rules, adjustable settings) used by every later phase | `backend/app/strategies/` |
| Strategy library | 9 beginner strategies: buy and hold, moving-average crossover, trend pullback, RSI reversal, Bollinger bounce, 20-day breakout, MACD momentum, Ichimoku Cloud trend, support and resistance (manual) | `backend/app/strategies/library/` |
| Backtester | Runs a strategy over history bar by bar, with no look-ahead; models spreads, commission and slippage; real-shares or CFD mode (leverage, overnight financing, UK stamp duty on UK shares) | `backend/app/backtest/` |
| Results report | Net profit in GBP, win rate, average win vs average loss, profit factor, maximum drawdown, longest losing run, number of trades, equity curve, every trade drawn on the chart | Backtest page |
| Buy-and-hold comparison | Every result shown beside simply holding the market over the same period | Results report |
| Honest-result warnings | Flags fewer than 30 trades, results that vanish once costs are added, results that lose to buy-and-hold | Results report |
| Risk guard | Enforces the risk rules on every simulated order: stop-loss required, 1% risk per trade, daily and drawdown limits, leverage caps | `backend/app/risk/` |
| Position-size calculator | Trade size from account size in GBP, risk percentage and stop distance | Tools page |
| Goal calculator | Monthly income target plus money available gives the return needed, compared with your backtests, with a realism verdict | Tools page |
| Signal assistant | For the chart on screen: a live checklist per strategy, a status (No setup / Watch: forming / Setup complete), historical evidence for that signal on that market, suggested stop-loss and position size, plain-English reasoning | Panel beside the chart |
| Strategy pages | Rules in plain English, when each strategy tends to work and fail, adjustable settings, a suggested exercise | Learn section |

**Gate:** a backtest of the moving-average crossover on one market matches a hand-checked spreadsheet trade for trade, including costs.

**Done when**

- [ ] All 9 strategies backtest on forex, commodities and US stocks
- [ ] Results include costs and a buy-and-hold comparison every time
- [ ] Signal assistant shows checklist, status, evidence and trade plan for every strategy
- [ ] Position-size and goal calculators work in GBP
- [ ] Unit tests cover every strategy rule and the cost model; the safety test still passes

## Phase 3: paper trading and the built-in coach

Phase 3 lets you trade live prices with pretend money, by hand or automatically, while the built-in coach teaches and checks your discipline.

| Part | What it does | Where it lives |
| --- | --- | --- |
| Paper accounts (**done**) | Pretend GBP balances, each set to real shares or CFD; any number of accounts, e.g. one per strategy; delete with a typed confirmation | `backend/app/paper/` |
| Price orders (**done**) | From the chart's trade planner, "when the price reaches my entry": buy stop / buy limit / sell stop / sell limit with a stop-loss and optional target and expiry; dotted lines on the chart; the worker fills them at the level (or the gap price) through the same safeguards, or fails them with an alert | Trade planner, Paper page, `backend/app/paper/orders.py` |
| Manual paper trading (**done**) | Buy or sell from the chart, with stop-loss and target, through the pre-trade checklist and risk guard | Trade panel on the chart |
| Automatic forward tests (**done**) | A strategy trades a paper account on live prices with the same rules as the backtester; results shown beside the backtest's; a tested basket starts on paper with one button; each run's trades open on the chart | Paper page, background worker |
| Scalping strategies (**done**) | London open breakout, 5-minute trend pullback and 1-minute range fade, with UK session hours, profit targets and months of short-candle history; in Backtest, Research and automatic paper runs | Strategy library |
| Monthly top-ups | Adds a fixed amount to a paper account each month, matching how the real pot will grow | Account settings |
| Background worker (**done**) | Fetches prices on schedule and fills paper orders, stops and targets | Separate container |
| Trade journal | Notes, chart snapshot, reason for entry and a mood tag on every trade | Journal page |
| Performance dashboard (**done**) | Equity curve, win rate, average win vs average loss, expectancy, drawdown, rule score, per account | Dashboard page |
| Learning path | The 12-week course, unlocked week by week, each with short lessons, a quiz and one task in the app | Learn section |
| Pre-trade checklist (**done**) | Trend direction, stop-loss, position size and a one-sentence reason; the trade can't be placed until complete | Trade panel |
| Rule score (**done**) | Each trade scored on whether the plan was followed, separately from profit | Journal and dashboard |
| Weekly review (**done**) | A guided 20-minute review: best and worst trade, rules broken, one focus for next week | Weekly page |
| Automatic feedback (**done**) | Rule-based warnings, e.g. moving stops further away, trading more after losses, losses twice the size of wins | Dashboard |
| Coach export (**done**) | One click copies a summary of a backtest or the week's trades and journal, ready for a coaching session with Claude | Dashboard and backtest pages |
| Basket backtest (**done**) | One strategy on several markets at once from one shared account, with the open-risk limit, shared margin and account limits across the basket; compared with each market alone and with holding the basket | Backtest page → Basket of markets |

**Gate:** paper accounts run for four weeks without errors, and every fill matches the price recorded at that moment.

**Done when**

- [ ] Manual and automatic paper trading both work on forex, commodities and US stocks
- [ ] Every paper order passes the pre-trade checklist and risk guard
- [ ] Journal, dashboard, weekly review and rule score are in use
- [ ] Weeks 1 to 12 of the learning path are written and unlock in order
- [ ] Forward-test results line up with backtests of the same period, allowing for costs

## Phase 4: practice and stress-testing

Phase 4 adds ways to practise without waiting for the market, to build your own strategies without code, and to catch strategies that only looked good by luck.

| Part | What it does | Where it lives |
| --- | --- | --- |
| Market replay | Pick a past date, hide the future, and step through bar by bar, placing paper trades as if live; scored at the end | Replay page |
| No-code strategy builder | Build rules from blocks, e.g. "when RSI is below 30 and price is above the 200 EMA, buy; stop 2 x ATR below"; saved strategies work everywhere a library strategy does | Builder page |
| Walk-forward test (**done**) | Tunes settings on one stretch of history and checks them on the next, unseen stretch, repeated across the data (9 stretches: tune on 3, trade the next, 6 times) | Backtest page, both tabs, on demand |
| Monte Carlo test (**done**) | Reshuffles the order of past trades thousands of times to show the range of drawdowns and outcomes luck could produce | Backtest page |
| Robustness verdict (**done on the Backtest page**) | Labels each strategy: Reject / Watchlist / Incubate / Candidate, from seven checks: unseen years profitable, edge kept from tuning, unseen stretches profitable, neighbouring settings, markets, Monte Carlo, enough trades | Walk-forward card; strategy pages later |
| Alerts (**Telegram done**) | Automatic trades opening and closing, stops and targets hit, runs or accounts pausing, backup problems, weekly research; price levels and signal setups still to come | Settings → Alerts |
| Economic calendar | Upcoming interest-rate decisions, jobs and inflation reports, shown on the chart; a warning before placing a trade shortly before a high-impact event | Panel beside the chart, trade panel |
| Event pause for automatic runs | Optional per run: no new entries in a window around high-impact events (open trades keep their stop-losses) | Automatic run settings |
| Market details and headlines (**done for the chart's hover card**) | Who a company is, its sector, size and a Wikipedia summary; what a currency, commodity, index or bond is and what moves it; recent headlines for US shares and funds (Alpha Vantage, at most 15 lookups a day so UK share prices keep some allowance) | ⓘ by the market name, and beside the market list |
| News alerts | A Telegram alert when a major story breaks about a market you hold a paper trade in | Settings → Alerts |

**Gate:** a deliberately overfitted test strategy is correctly labelled Reject by the robustness checks. **Passed** (`tests/test_walkforward.py`: strategies tuned on pure random-walk prices are rejected; a trend-follower on trending prices is not).

**Done when**

- [ ] Market replay works on any market and timeframe with history
- [ ] Builder strategies backtest, paper trade and feed the signal assistant like library strategies
- [x] Walk-forward and Monte Carlo results appear on every backtest (walk-forward on demand, a button on the result)
- [ ] Alerts arrive by email and, if set up, Telegram
- [ ] Economic calendar shows the coming week's major events
- [ ] Headlines and news alerts work for markets you hold, and never open, close or change a trade

**News is information, not a trade signal.** Free feeds arrive after prices have already moved, past news can't be
backtested, and judging a headline would mean an AI making trade decisions. So nothing in this section places, closes or
changes a trade; the only automatic effect is the optional event pause, which stops new entries and nothing else.

## Phase 5: AI coach, graduation and export

Phase 5 adds a coach you can talk to about your own trading, the bar a strategy must clear before real money is even considered, and a way to take strategies to TradingView.

| Part | What it does | Where it lives |
| --- | --- | --- |
| AI coach chat (optional) | A chat panel that reads your journal, trades, backtests and progress, and explains results, runs the weekly review with you and quizzes weak spots; read-only, so it can't trade or change settings | Coach panel |
| Coach running costs | Runs on your Claude plan's monthly Agent SDK credit if that works for a personal app, otherwise Anthropic's pay-as-you-go API; a monthly spending cap in the app switches it off when reached | Settings |
| Graduation checklist | The criteria a strategy must meet on paper before it can be considered for real money (proposed defaults below) | Strategy pages |
| Pine Script export | Turns a tested strategy into TradingView Pine Script, to view it there | Strategy pages |

**Proposed graduation criteria** (all must be met; adjustable only to be stricter):

- At least 3 months and 50 trades of automatic forward testing on paper
- Profitable after costs, and ahead of buy-and-hold on a risk-adjusted basis
- Maximum drawdown within the account's limit (10% default)
- Robustness verdict of Candidate or better
- Paper results close to the backtest of the same period (no large drift)
- Rule score of 90% or more on your manual trades over the last month

**Gate:** the AI coach answers questions about a sample journal correctly, refuses to place trades or change settings, and stops at the spending cap.

**Done when**

- [ ] AI coach works on your plan's credit or a capped API key, or stays switched off
- [ ] Graduation checklist shows pass or fail per strategy, criterion by criterion
- [ ] Pine Script export works for every library strategy
- [ ] Phases 2 to 5 pass their gates together: ready for launch

## Before launch: backups and hardening

Before the launch version is called finished, your data must be backed up off the server and the setup checked once more.

- [x] **Nightly backups:** the database is copied every night, test-restored into a scratch database, encrypted and sent to a Backblaze B2 bucket with a write-only key; about 30 days are kept (see `docs/BACKUPS.md`)
- [ ] **Restore test:** a backup is restored into a spare database and checked, so backups are known to work
- [ ] **Database upgrades:** a migration tool is added so future versions update the database without losing data
- [ ] **Health monitor:** a free uptime check emails you if the site stops responding
- [ ] **Logs kept tidy:** app logs rotate so they never fill the account's disk
- [ ] **Security review:** dependencies updated, sign-in and password gate re-tested, safety test passing
- [ ] **Deploy guide updated** for everything added in phases 2 to 5

## Phase 6: optional real-money trading (after launch)

Phase 6 is built only after launch, ships switched off, and unlocks one strategy at a time once that strategy has graduated on paper.

| Part | What it does |
| --- | --- |
| Live gateway | A separate, isolated container: the only code allowed to send real orders. The safety test permits order code there and nowhere else |
| Broker connectors | Real shares first through Interactive Brokers (no leverage). OANDA and Capital.com, for leveraged CFDs, only if you deliberately choose them later. Each connector is tested on the broker's demo account first |
| Trade-only keys | Withdrawals disabled, restricted to your server where the broker allows, encrypted, and readable only by the gateway |
| Switching it on | Needs your password plus a fresh authenticator code; logged |
| Confirm mode first | The app proposes each live trade and you approve it with one tap |
| Automatic mode | Unlocked per strategy after a month in confirm mode without a rule breach |
| Limits in pounds | Maximum money per strategy, and maximum loss per day and per week; hitting one stops the strategy |
| Broker-held stops | Every order is sent with its stop-loss attached, so it holds even if your server goes down |
| Live price orders | The paper price orders carried over: sent to the broker as native stop or limit entry orders with the stop-loss attached, so the broker holds them. You confirm each order once when placing it, with the pounds at risk shown; it then fills at your price without asking again, still within the pound limits and the kill switch |
| Kill switch | One button, and a Telegram command, close all live positions and switch the gateway off |
| Health and drift checks | No new trades on stale prices or a dropped connection; live results compared with the paper twin, with a pause on large gaps |
| Audit log | Every live order, approval and setting change recorded and uneditable |
| PAPER / LIVE labels | Every screen shows which mode it's in, in different colours |

**Before building it:** reconsider moving the app to its own small server, since your cPanel server is shared and its firewall stays as it is. Check tax treatment, such as using a Stocks and Shares ISA, with a qualified adviser.

**Gate:** every connector places, modifies and closes orders correctly on the broker's demo account, stops are attached, and the kill switch closes everything.

**Done when**

- [ ] Gateway, connectors and kill switch pass on demo accounts
- [ ] A graduated strategy runs in confirm mode with limits in pounds
- [ ] Live and paper results are compared automatically

## Open decisions

- [x] **Backup location:** Backblaze B2, encrypted, nightly at 02:30 UTC with a test restore (see `docs/BACKUPS.md`)
- [ ] **Graduation criteria:** keep the proposed defaults in phase 5, or make any stricter
- [ ] **Seconds charts:** add 5, 10, 15 and 30-second timeframes for OANDA markets (viewing only), and whether to add a live tick chart
- [ ] **Economic calendar source:** confirm a free source whose terms allow this use during phase 4 (needs adding to the app's list of allowed web addresses). Headlines and company details: Alpha Vantage and Wikipedia (decided)
- [ ] **AI coach:** try it on your Claude plan's monthly credit first, or leave it switched off
- [ ] **Before phase 6:** stay on the cPanel server or move the app to its own small server; choose a real-shares platform and whether to use a Stocks and Shares ISA
