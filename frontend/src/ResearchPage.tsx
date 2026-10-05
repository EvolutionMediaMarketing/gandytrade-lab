import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { displayCode } from "./MarketPicker";
import type { AutoPrefill, ResearchAcross, ResearchCheck, ResearchJob, ResearchOptions, ResearchRow, BasketInit } from "./types";

const POLL_MS = 5000;
const CHECK_LABEL: Record<ResearchCheck, string> = {
  profitable: "Profitable after costs",
  enoughTrades: "Enough trades",
  drawdown: "Worst fall within limit",
  robust: "Robust to settings",
  recent: "Still working recently",
};
const CHECK_SHORT: Record<ResearchCheck, string> = {
  profitable: "Profit", enoughTrades: "Trades", drawdown: "Fall", robust: "Robust", recent: "Recent",
};
const TF_LABEL: Record<string, string> = { "5m": "5 minutes", "15m": "15 minutes", "4h": "4 hours", "1d": "Daily", "1w": "Weekly" };

const pct = (v: number | null | undefined, sign = true) =>
  v === null || v === undefined ? "–" : `${sign && v > 0 ? "+" : ""}${v.toFixed(1)}%`;
/** "4.0 yrs", or "6 months" for tests shorter than a year (never scaled up to a yearly figure). */
const span = (years: number) => (years >= 1 ? `${years.toFixed(1)} yrs` : `${Math.max(1, Math.round(years * 12))} month${Math.round(years * 12) === 1 ? "" : "s"}`);
const dir = (d: string) => (d === "both" ? "Buys and shorts" : "Buys only");
const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "–";

interface Props {
  onAuthError: (err: unknown) => void;
  onBacktest: (row: { symbol: string; strategy: string; timeframe: string; direction: string }) => void;
  onRunOnPaper: (p: AutoPrefill) => void;
  onBasket?: (b: BasketInit) => void;
}

export default function ResearchPage({ onAuthError, onBacktest, onRunOnPaper, onBasket }: Props) {
  const [options, setOptions] = useState<ResearchOptions | null>(null);
  const [jobs, setJobs] = useState<ResearchJob[]>([]);
  const [shown, setShown] = useState<ResearchJob | null>(null);
  const [markets, setMarkets] = useState<string[] | null>(null);
  const [strategyPick, setStrategyPick] = useState<string[] | null>(null);
  const [sectorPick, setSectorPick] = useState<string[]>([]);
  const [timeframes, setTimeframes] = useState<string[]>(["1d"]);
  const [error, setError] = useState<string | null>(null);

  const loadJobs = useCallback((background = false) => {
    api.researchJobs(background).then((r) => setJobs(r.jobs)).catch(onAuthError);
  }, [onAuthError]);

  useEffect(() => {
    api.researchOptions().then((o) => { setOptions(o); setTimeframes(o.defaultTimeframes); }).catch(onAuthError);
    loadJobs();
  }, [loadJobs, onAuthError]);

  const active = jobs.find((j) => j.status !== "done");
  const latestDone = jobs.find((j) => j.status === "done");

  // While a scan runs, check on it every few seconds.
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => { if (document.visibilityState === "visible") loadJobs(true); }, POLL_MS);
    return () => window.clearInterval(t);
  }, [active, loadJobs]);

  // Show the newest finished scan unless you picked an older one.
  const [picked, setPicked] = useState<number | null>(null);
  const showId = picked ?? latestDone?.id ?? null;
  useEffect(() => {
    if (showId === null) { setShown(null); return; }
    if (shown?.id === showId) return;
    api.researchJob(showId).then(setShown).catch(onAuthError);
  }, [showId, shown?.id, onAuthError]);

  // Markets on offer: the default basket, or the sectors you've picked (all of them ticked to start with).
  const sectorMarkets = (options?.sectors ?? []).filter((x) => sectorPick.includes(x.name)).flatMap((x) => x.markets);
  const offered = sectorPick.length
    ? [...new Map(sectorMarkets.map((m) => [m.code, m])).values()]
    : (options?.basket ?? []).map((b) => ({ ...b, provider: "oanda" }));
  const chosen = markets ?? offered.map((b) => b.code);
  const shareCount = offered.filter((m) => chosen.includes(m.code) && m.provider !== "oanda").length;
  const missing = (options?.sectors ?? []).filter((x) => sectorPick.includes(x.name)).flatMap((x) => x.missing);
  const allStrategies = options?.strategies ?? [];
  const chosenStrategies = strategyPick ?? allStrategies.map((s) => s.key);
  const shortTf = timeframes.some((t) => t === "5m" || t === "15m");
  const onlyScalpers = chosenStrategies.length > 0
    && chosenStrategies.every((k) => allStrategies.find((s) => s.key === k)?.intradayOnly);
  const scalpersIgnored = !shortTf && chosenStrategies.some((k) => allStrategies.find((s) => s.key === k)?.intradayOnly);

  function start() {
    setError(null);
    const all = chosenStrategies.length === allStrategies.length;
    api.startResearch({ markets: chosen, timeframes, strategies: all ? [] : chosenStrategies }).then(() => loadJobs()).catch((err) => {
      onAuthError(err);
      setError(err instanceof Error ? err.message : "Couldn't start the scan.");
    });
  }

  return (
    <div className="page research">
      <header className="research-head">
        <h2>Research</h2>
        <p className="muted">
          Backtests every strategy, on its default settings, across a basket of markets, with the same costs and 1% risk as the
          Backtest page. Each result faces five checks, and only those that pass all five are shortlisted for paper trading.
          A fresh scan runs by itself every week.
        </p>
      </header>

      <div className="card">
        <h3>Scan</h3>
        <div className="form-row">
          <span className="field-label">Timeframes</span>
          <div className="segmented" role="group" aria-label="Timeframes">
            {(options?.timeframes ?? ["5m", "15m", "4h", "1d", "1w"]).map((t) => (
              <button key={t} type="button" className={timeframes.includes(t) ? "on" : ""}
                onClick={() => setTimeframes((cur) => cur.includes(t) ? (cur.length > 1 ? cur.filter((x) => x !== t) : cur) : [...cur, t])}>
                {TF_LABEL[t] ?? t}
              </button>
            ))}
          </div>
        </div>
        <div className="form-row">
          <span className="field-label">
            Sectors{" "}
            {sectorPick.length > 0 && (
              <button type="button" className="link-button small-text" onClick={() => { setSectorPick([]); setMarkets(null); }}>back to the mixed basket</button>
            )}
          </span>
          <div className="chips">
            {(options?.sectors ?? []).map((x) => {
              const on = sectorPick.includes(x.name);
              return (
                <button key={x.name} type="button" className={on ? "chip on" : "chip"}
                  title={x.markets.map((m) => m.name).join(", ")}
                  onClick={() => { setSectorPick(on ? sectorPick.filter((n) => n !== x.name) : [...sectorPick, x.name]); setMarkets(null); }}>
                  {x.name}
                </button>
              );
            })}
          </div>
          <span className="muted small-text">Pick one or more sectors to scan their markets instead of the mixed basket.</span>
        </div>
        <div className="form-row">
          <span className="field-label">Markets ({chosen.length})</span>
          <div className="chips">
            {offered.map((b) => {
              const on = chosen.includes(b.code);
              return (
                <button key={b.code} type="button" className={on ? "chip on" : "chip"} title={b.name}
                  onClick={() => setMarkets(on ? chosen.filter((c) => c !== b.code) : [...chosen, b.code])}>
                  {displayCode(b.code)}
                </button>
              );
            })}
          </div>
        </div>
        <div className="form-row">
          <span className="field-label">
            Strategies ({chosenStrategies.length}){" "}
            <button type="button" className="link-button small-text" onClick={() => setStrategyPick(null)}>all</button>
            {" · "}
            <button type="button" className="link-button small-text" onClick={() => setStrategyPick(allStrategies.filter((s) => !s.intradayOnly).map((s) => s.key))}>no scalping</button>
            {" · "}
            <button type="button" className="link-button small-text" onClick={() => {
              setStrategyPick(allStrategies.filter((s) => s.intradayOnly).map((s) => s.key));
              if (!shortTf) setTimeframes(["5m"]);
            }}>scalping only</button>
          </span>
          <div className="chips">
            {allStrategies.map((st) => {
              const on = chosenStrategies.includes(st.key);
              return (
                <button key={st.key} type="button" className={on ? "chip on" : "chip"}
                  onClick={() => setStrategyPick(on ? chosenStrategies.filter((k) => k !== st.key) : [...chosenStrategies, st.key])}>
                  {st.name}
                </button>
              );
            })}
          </div>
        </div>
        {onlyScalpers && !shortTf && (
          <p className="warn caution small-text">Scalping strategies only run on short candles: tick 5 minutes or 15 minutes above.</p>
        )}
        {scalpersIgnored && !onlyScalpers && (
          <p className="muted small-text">The scalping strategies you've ticked are skipped on these timeframes; they only run on 5 and 15-minute candles.</p>
        )}
        {shareCount > 0 && (
          <p className="muted small-text">
            {shareCount} US share{shareCount === 1 ? "" : "s"} or fund{shareCount === 1 ? "" : "s"}: these are scanned on daily and weekly
            candles only, about three a minute to stay inside the free data allowance.
          </p>
        )}
        {missing.length > 0 && (
          <p className="muted small-text">Not in your market list, so left out (not on the free data plans, or the list hasn't downloaded yet): {missing.join(", ")}.</p>
        )}
        {shortTf && (
          <p className="muted small-text">
            5 and 15-minute scans use months of short candles, so they take longer: allow up to half an hour for the whole
            basket with every strategy. Fewer strategies or markets finish sooner.
          </p>
        )}
        {active ? (
          <div className="scan-progress">
            <p>{active.automatic ? "Weekly scan" : "Scan"} running: {active.message}</p>
            <div className="bar"><span style={{ width: `${active.total ? (active.done / active.total) * 100 : 0}%` }} /></div>
            <p className="muted small-text">It runs in the background: you can leave this page and come back.</p>
          </div>
        ) : (
          <button type="button" className="primary" disabled={!chosen.length || !chosenStrategies.length || (onlyScalpers && !shortTf)} onClick={start}>
            Run a new scan
          </button>
        )}
        {error && <p className="warn stop">{error}</p>}
        {jobs.filter((j) => j.status === "done").length > 1 && (
          <label className="form-row past-scans">
            <span className="field-label">Showing</span>
            <select value={showId ?? ""} onChange={(e) => setPicked(Number(e.target.value))}>
              {jobs.filter((j) => j.status === "done").map((j) => (
                <option key={j.id} value={j.id}>{when(j.finishedAt)}{j.automatic ? " (weekly)" : ""}</option>
              ))}
            </select>
          </label>
        )}
      </div>

      {!shown && !active && <div className="empty-state"><p className="muted">No scans yet. Run one above; it takes a few minutes.</p></div>}
      {shown?.summary && <Results job={shown} options={options} onBacktest={onBacktest} onRunOnPaper={onRunOnPaper} onBasket={onBasket} />}
    </div>
  );
}

function Results({ job, options, onBacktest, onRunOnPaper, onBasket }: {
  job: ResearchJob; options: ResearchOptions | null;
  onBacktest: Props["onBacktest"]; onRunOnPaper: Props["onRunOnPaper"]; onBasket?: Props["onBasket"];
}) {
  const s = job.summary!;
  const [showAll, setShowAll] = useState(false);
  const all = useMemo(() => [...(job.rows ?? [])].sort((a, b) => b.passed - a.passed || b.score - a.score), [job.rows]);
  const minTrades = options?.minTrades ?? 30;
  const maxDd = options?.maxDrawdownPct ?? 20;

  return (
    <>
      <p className="muted small-text">
        Scan finished {when(job.finishedAt)}: {s.tested} combinations of market, timeframe, strategy and direction
        {job.settings.strategies?.length ? `, for ${job.settings.strategies.length} chosen strateg${job.settings.strategies.length === 1 ? "y" : "ies"}` : ""}.
      </p>
      <p className="warn caution">
        Testing this many combinations means a few will look good by luck. That's why the checks include different settings and
        the most recent stretch of prices. Even so, treat the shortlist as ideas to test on paper, not as trades to place.
      </p>

      <div className="card">
        <h3>Shortlist: passed all five checks</h3>
        <ul className="check-key">
          <li><b>Profitable</b> after costs</li>
          <li><b>{minTrades}+ trades</b>, so it's not a few lucky ones</li>
          <li><b>Worst fall</b> no more than {maxDd}%</li>
          <li><b>Robust</b>: still profitable with shorter and longer settings</li>
          <li><b>Recent</b>: profitable over the latest third of the history</li>
        </ul>
        {s.shortlist.length === 0 ? (
          <p>
            Nothing passed all five checks. That's a common answer, and a useful one: it means no simple rule here has a reliable edge
            on these markets. Look at the near misses below, or try the weekly timeframe.
          </p>
        ) : (
          <div className="research-cards">
            {s.shortlist.map((r) => <RowCard key={key(r)} row={r} onBacktest={onBacktest} onRunOnPaper={onRunOnPaper} />)}
          </div>
        )}
      </div>

      {s.acrossMarkets.length > 0 && (
        <div className="card">
          <h3>Rules that held up on several markets</h3>
          <p className="muted small-text">
            Profitable and robust on two or more markets. A rule that works in several places is more believable than one that works in
            one, and running it on all of them gives more trades a year.
          </p>
          <div className="table-wrap">
            <table className="trades">
              <thead><tr><th>Strategy</th><th>Direction</th><th>Timeframe</th><th className="num">Held on</th><th>Markets</th><th className="num">Avg per year</th><th className="num">Trades/yr (all)</th><th></th></tr></thead>
              <tbody>
                {s.acrossMarkets.map((a: ResearchAcross) => (
                  <tr key={`${a.strategy}-${a.direction}-${a.timeframe}`}>
                    <td>{a.strategyName}</td><td>{dir(a.direction)}</td><td>{TF_LABEL[a.timeframe] ?? a.timeframe}</td>
                    <td className="num">{a.held} of {a.markets}</td>
                    <td>{a.heldMarkets.map((m) => displayCode(m.market)).join(", ")}</td>
                    <td className={`num ${a.avgAnnualPct >= 0 ? "up" : "down"}`}>
                      {a.years !== undefined && a.years < 1 ? `${pct(a.avgReturnPct ?? 0)} over ${span(a.years)}` : pct(a.avgAnnualPct)}
                    </td>
                    <td className="num">{a.tradesPerYear}</td>
                    <td>{onBasket && (
                      <button type="button" className="ghost small" title="Test these markets together, in one account"
                        onClick={() => onBasket({ markets: a.heldMarkets.map((m) => m.market), strategy: a.strategy, timeframe: a.timeframe, direction: a.direction })}>
                        Backtest as a basket
                      </button>
                    )}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {s.nearMisses.length > 0 && (
        <div className="card">
          <h3>Near misses: profitable, but failed one check</h3>
          <div className="research-cards">
            {s.nearMisses.map((r) => <RowCard key={key(r)} row={r} onBacktest={onBacktest} onRunOnPaper={onRunOnPaper} />)}
          </div>
        </div>
      )}

      <div className="card">
        <h3>
          All results{" "}
          <button type="button" className="link-button small-text" onClick={() => setShowAll((v) => !v)}>{showAll ? "hide" : `show all ${all.length}`}</button>
        </h3>
        {showAll && (
          <div className="table-wrap">
            <table className="trades research-all">
              <thead>
                <tr>
                  <th>Market</th><th>Strategy</th><th>Dir.</th><th>TF</th><th className="num">Per year</th><th className="num">Trades</th>
                  <th className="num">Worst fall</th><th className="num">Hold</th>
                  {(options?.checks ?? []).map((c) => <th key={c} title={CHECK_LABEL[c]}>{CHECK_SHORT[c]}</th>)}
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {all.map((r) => (
                  <tr key={key(r)}>
                    <td>{displayCode(r.market)}</td><td>{r.strategyName}</td><td>{r.direction === "both" ? "Both" : "Buys"}</td><td>{r.timeframe}</td>
                    <td className={`num ${(r.annualPct ?? r.returnPct) >= 0 ? "up" : "down"}`}
                      title={r.years < 1 ? `Result over ${span(r.years)}: too short to give a yearly figure` : undefined}>
                      {r.years >= 1 ? pct(r.annualPct) : `${pct(r.returnPct)} (${span(r.years)})`}
                    </td>
                    <td className="num">{r.trades}</td>
                    <td className="num">{pct(-r.maxDrawdownPct, false)}</td>
                    <td className="num muted">{pct(r.buyHoldReturnPct)}</td>
                    {(options?.checks ?? []).map((c) => <td key={c} className={r.checks[c] ? "up" : "down"}>{r.checks[c] ? "✓" : "✗"}</td>)}
                    <td><button type="button" className="ghost small" onClick={() => onBacktest(backtestOf(r))}>Backtest</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {job.skipped && job.skipped.length > 0 && (
          <p className="muted small-text">Not tested: {job.skipped.map((k) => `${displayCode(k.market)} ${k.timeframe} (${k.reason})`).join("; ")}</p>
        )}
      </div>
    </>
  );
}

const key = (r: ResearchRow) => `${r.market}-${r.timeframe}-${r.strategy}-${r.direction}`;
const backtestOf = (r: ResearchRow) => ({ symbol: r.market, strategy: r.strategy, timeframe: r.timeframe, direction: r.direction });

function RowCard({ row: r, onBacktest, onRunOnPaper }: { row: ResearchRow; onBacktest: Props["onBacktest"]; onRunOnPaper: Props["onRunOnPaper"] }) {
  const failed = (Object.keys(r.checks) as ResearchCheck[]).filter((c) => !r.checks[c]);
  return (
    <div className="research-card">
      <div className="research-card-head">
        <b>{r.strategyName}</b>
        <span>{displayCode(r.market)} <span className="muted">{r.name}</span></span>
        <span className="muted">{TF_LABEL[r.timeframe] ?? r.timeframe} · {dir(r.direction)}</span>
      </div>
      <dl className="facts compact">
        {r.years >= 1 && <><dt>Per year</dt><dd className={(r.annualPct ?? 0) >= 0 ? "up" : "down"}>{pct(r.annualPct)}</dd></>}
        <dt>Over {span(r.years)}</dt><dd className={r.years < 1 ? (r.returnPct >= 0 ? "up" : "down") : ""}>{pct(r.returnPct)}</dd>
        <dt>Trades</dt><dd>{r.trades}{r.tradesPerYear !== null ? (r.years >= 1 ? ` (${r.tradesPerYear}/yr)` : ` (${Math.round(r.tradesPerYear / 12)} a month)`) : ""}</dd>
        <dt>Win rate</dt><dd>{pct(r.winRate, false)}</dd>
        <dt>Average R</dt><dd>{r.avgR?.toFixed(2) ?? "–"}</dd>
        <dt>Worst fall</dt><dd>{pct(-r.maxDrawdownPct, false)}</dd>
        {r.costShare != null && <><dt>Costs took</dt><dd className={r.costShare > 50 ? "down" : ""}>{r.costShare}% of the profit before costs</dd></>}
        <dt>Other settings</dt><dd>{r.variantReturns.map((v) => pct(v)).join(" / ")}</dd>
        <dt>Latest third</dt><dd className={r.recentNet >= 0 ? "up" : "down"}>£{r.recentNet.toFixed(2)} from {r.recentTrades} trades</dd>
        <dt>Buy and hold</dt><dd>{pct(r.buyHoldReturnPct)}, worst fall {pct(-r.buyHoldDrawdownPct, false)}</dd>
      </dl>
      <p className="small-text">
        {r.beatsBuyHold ? "Beat buy-and-hold." : r.smootherThanBuyHold ? "Made less than buy-and-hold, but with a better return for the falls it took." : "Didn't beat buy-and-hold, and wasn't smoother either."}
        {failed.length > 0 && <span className="down"> Failed: {failed.map((c) => CHECK_LABEL[c].toLowerCase()).join(", ")}.</span>}
      </p>
      <div className="planner-actions">
        <button type="button" className="ghost small" onClick={() => onBacktest(backtestOf(r))}>Open in Backtest</button>
        <button type="button" className="small" onClick={() => onRunOnPaper({ symbol: r.market, timeframe: r.timeframe, strategy: r.strategy, direction: r.direction })}>
          Test on paper automatically
        </button>
      </div>
    </div>
  );
}
