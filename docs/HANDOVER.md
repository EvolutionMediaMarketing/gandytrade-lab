# Handover: where GandyTrade Lab stands

Last updated 5 October 2026. Read this first when picking the project up in a new session; `docs/ROADMAP.md`
has the full plan and `CLAUDE.md` the hard rules.

## Working setup

- Repo: `EvolutionMediaMarketing/gandytrade-lab`. Work on branch `phase-3`, push with `git push origin phase-3 phase-3:main`.
- Live at https://gandytrade.co.uk (Apache password gate, then app login with authenticator 2FA). Single user, GBP.
- Server: WHM/cPanel VPS (AlmaLinux), app runs as cPanel user `gandytradeco` in rootless Podman (app on 127.0.0.1:8601,
  Postgres and a worker in their own containers). Containers can cap memory and process counts on this server, not CPU.
- Update command (run as root on the server):
  `cd /home/gandytradeco/gandytrade-lab && runuser -u gandytradeco -- git pull --ff-only && bash deploy/scripts/as-app-user.sh deploy/scripts/update.sh`
  It backs up the database first, builds at low priority (nice/ionice), runs migrations at start-up and restarts the app and worker.
- Check after a reboot: `runuser -u gandytradeco -- env XDG_RUNTIME_DIR=/run/user/$(id -u gandytradeco) systemctl --user is-active gandytrade-db gandytrade-app gandytrade-worker` (expect `active` three times).
- Backups: nightly encrypted to Backblaze B2 at 02:30 UTC with a test restore (`docs/BACKUPS.md`).
- Alerts: Telegram bot (trades, problems, research, weekly review reminder). Secrets only in `~/gandytrade/app.env`.
- Tests: `cd backend && python -m pytest -q` (269 passing). Frontend: `cd frontend && npm run build`. Latest migration: 0014.

## What's built (phases 2 and 3, plus parts of 4)

- Backtester (one market and baskets of up to 12 markets on one shared account), 12 strategies including three scalpers,
  real OANDA spreads, buy-and-hold comparison, drawdown-limit date shown and an optional "keep testing past the drawdown
  limit" (tests only), strategy settings on the basket form, Monte Carlo check (2,000 resampled histories) on every backtest.
- History: full download never reaches back before 2002 (fixes weekly/monthly tests stuck at 500 candles); daily keeps
  5,000 candles (about 18 years, from 2008).
- Research page (scans by market, sector and chosen strategies), signal assistant, risk guard (1% risk, 10% open-risk
  limit, 3% daily loss, 20% drawdown pause).
- Paper trading: manual (with pre-trade checklist and journal) and automatic runs; "Run this basket on paper" starts one run
  per market on a new or chosen account in one go (all or nothing), optionally stopping old runs; max 10 runs at once.
  Each run lists its trades; click one to see it on the chart, or show all of a run's trades on one chart.
- Dashboard with automatic feedback and coach export, weekly review, Telegram alerts.
- **Walk-forward check and robustness verdict** (5 Oct 2026, `backend/app/backtest/walkforward.py`): a button on every
  backtest result (one market and basket). History split into 9 stretches; tune on 3 (your settings, every length
  ×0.5/×0.75/×1.5/×2, and the standard settings), trade the next unseen stretch, 6 times, balance carried forward. Seven
  checks give Reject / Watchlist / Incubate / Candidate. Phase 4 gate passed: strategies tuned on random-walk prices are
  rejected (`tests/test_walkforward.py`). Runs synchronously (about 60 backtests, a few seconds), one at a time.
- **Price orders** (5 Oct 2026, `backend/app/paper/orders.py`, migration 0013): in the chart's trade planner, "When the
  price reaches my entry" places a buy stop / buy limit / sell stop / sell limit on a paper account (the kind follows
  where the entry line sits against the price), with expiry (until cancelled, end of day, end of week, 30 days). Dotted
  amber lines on the chart; listed in the planner and on the Paper page with Cancel. The worker checks them each pass
  (OANDA every minute), fills at the level or the gap price through `paper.place()` (all safeguards; sized on the balance
  then), counts the trade as yours (`source="manual"`), and alerts on fill, failure or expiry. Paper only; live price
  orders are in the Phase 6 plan (broker-held, confirmed once at placement).
- **Trailing stops and order upgrades** (6 Oct 2026): the planner's stop-loss and target move with the entry (toggle, on by
  default) and the stop distance is shown as a multiple of the daily move. "Fixed / Trailing" stop when placing (now, at a
  price, or at the open) and "Trail it" on open manual trades: the stop follows the best price on finished candles,
  `trail_distance` behind, and only tightens (`paper.trail_step`). Setting the stop yourself on a trailing trade returns 409
  until confirmed, then cancels trailing. Not for automatic runs. "When the market opens" orders (`direction == 0`) fill at
  the first candle's open after a closed market opens, or fail if it gaps past the stop. The Paper page lists every
  waiting order across accounts (click to open the chart; edit price, stop, target, trailing, expiry; cancel), with
  per-account order history below. Migration 0014.
- **Journal page** (6 Oct 2026, `frontend/src/JournalPage.tsx`, `GET /api/paper/journal`): every trade from every account,
  newest first (up to 2,000), filterable by text, account, market, open/closed, yours/automatic, result, mood, lesson
  written, rule broken and date; filters remembered in the browser. Click a row for the journal drawer; Chart opens it.
- Market details hover card (ⓘ by the market name, and beside the market list): Wikipedia summary, Alpha Vantage
  sector/size and US headlines (at most 15 Alpha Vantage lookups a day), hand-written notes for currencies,
  commodities, indices and bonds. Information only.

## Strategy findings so far (backtests, 6-market basket: gold, silver, Brent, corn, Nasdaq 100, Japan 225)

| Test | Result |
| --- | --- |
| 20/10 breakout, daily, buys only | +5.2%, profit factor 1.04, costs 88% of gross profit |
| 20/10 breakout, weekly, buys only (2006–2026) | +42% kept going (1.7%/yr), profit factor 1.6, worst fall 23%; stopped by 20% limit May 2019 |
| Buys and shorts (daily and weekly) | Lost money both times: shorts hurt |
| **55/10 breakout, daily, buys only, 1% risk** | +147% kept going (5.1%/yr), PF 1.68, worst fall 22.3%, all 6 markets profitable; limit hit July 2017 |
| 55/10 at 2% risk | +415% (9.4%/yr) but worst fall 40%, limit hit May 2010: same efficiency, more pain |
| **55/20 breakout, daily, buys only, 1% risk** | +230% kept going (6.8%/yr), PF 2.08, avg 0.60R, worst fall 28.5%, all 6 markets profitable; limit hit Oct 2015 |
| Holding the basket | +524% (about 10.6%/yr) with a 39–50% worst fall |

Conclusions: buys only; slower breakouts beat costs; 1% risk; 20% limit treated as a pause to review, not an ending;
holding beat trading on return but with much deeper falls. A **55/20 daily basket** was started on paper on 5 October
2026 (account "20-day breakout (55/20) basket 1d", 6 automatic runs).

**Monte Carlo for the 55/20 basket** (5 Oct 2026; all history, kept going past the limit, £200, 1% risk, 241 trades,
2,000 reshuffles): typical worst fall 15%, 1 in 20 25%, 1 in 100 30%; middle result +264% (9 in 10 between +66% and
+743%); 0% ended below the start; 20% limit reached in 15%; losing runs 10 typical, 15+ in 1 in 20. The backtest's own
order was on the unlucky side (only 5% of reshuffles fell further), so the result doesn't depend on lucky ordering.
Caveat: the reshuffle replays trades one at a time, but the basket holds several at once and they often fall together,
so real falls run deeper (backtest 28.5% vs 24% replayed). Treat about 30% as the realistic bad case.
It does not test whether 55/20 was picked to fit this history (walk-forward check does that).

**Judging the paper basket:** about 13 trades a year, so 6–12 months is far too few to judge on results. Expect about 37%
winners. Losing runs up to about 15 and falls up to about 25–30% are within normal. A 20% pause is plausible:
review, don't abandon. Look again at about 40 trades (around 3 years). Worry if average R is at or below zero by then,
if a losing run passes 15–16, or if a fall goes well past 30%. Before that, check only that trades match the backtest's
rules and costs (fills, spreads, stops).

## Next steps (user's choice)

1. ~~Rerun the 55/20 basket backtest to read its Monte Carlo card~~ (done 5 Oct, figures above).
2. Phase 3 remaining: monthly top-ups for paper accounts; the 12-week learning path.
3. Phase 4: ~~walk-forward check and robustness verdict~~ (done; run it on the 55/20 basket); economic calendar (source to
   choose); market replay; strategy builder. Later: show each strategy's latest verdict on strategy pages.
4. Before launch: health monitor, security review.

## Server incident, 5 October 2026 (not the app)

A WordPress xmlrpc.php password-guessing attack (mainly from 34.73.180.179, a Google Cloud machine) hit most WordPress
sites on the server; load reached about 27. Fixed with a WHM Include Editor rule (Pre VirtualHost, All Versions):

```
<LocationMatch "xmlrpc\.php$">
    Satisfy All
    Require all denied
    ErrorDocument 403 "Forbidden"
</LocationMatch>
```

`Satisfy All` is needed because httpd.conf has cPanel's `Satisfy Any` / `Allow from all`; without it, `Require` rules are
ignored. ModSecurity is installed with the engine on but switched off for almost every domain, so ModSecurity rules
(two were added, ids 1990001–2) only reach a few sites. Firewall: none (ImunifyAV only, no CSF/Imunify360).
Retired three finished Plate Wizard setup scripts from amtestdomain1.co.uk's mu-plugins to
`/home/amtestdomain1co/pwc-retired/`. ImunifyAV flags the app's compiled Python libraries (reason SMW-HEUR-ELF, under
`/home/gandytradeco/.local/share/containers/`) as "infected": false positives. Checked 5 Oct: 5,647 files matched
their packages' published hashes, 0 mismatches. Never use "Clean up all" on them; add that folder to ImunifyAV's
Ignore List. Open server follow-ups: Plate Wizard plugin security review, client admin
users/passwords, why ModSecurity is off per domain, robots.txt for glitteringstar.co.uk's crawler load.
