import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import ChartView, { ChartMarker } from "./ChartView";
import EquityChart from "./EquityChart";
import MonteCarloCard from "./MonteCarloCard";
import MarketPicker, { displayCode } from "./MarketPicker";
import type {
  BacktestRequest, BacktestResult, BacktestSummary, Catalogue, ChartData, CostSettings, StrategiesResponse, SymbolInfo, AutoPrefill,
} from "./types";
import type { Time } from "lightweight-charts";

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"];
const YEARS = [
  { v: 0, label: "All" }, { v: 1, label: "1 yr" }, { v: 3, label: "3 yrs" }, { v: 5, label: "5 yrs" }, { v: 10, label: "10 yrs" },
];
const COST_FIELDS: { key: keyof CostSettings; label: string; unit: string; help: string }[] = [
  { key: "spread_pct", label: "Spread", unit: "%", help: "Gap between the buy and sell price. Half is paid going in, half coming out." },
  { key: "slippage_pct", label: "Slippage", unit: "%", help: "Fills a little worse than the price you saw, on every order." },
  { key: "commission_gbp", label: "Commission", unit: "£ per order", help: "Fixed dealing charge for each buy or sell." },
  { key: "fx_fee_pct", label: "Currency fee", unit: "%", help: "Charged when your pounds are converted, e.g. to buy US shares." },
  { key: "stamp_duty_pct", label: "Stamp duty", unit: "%", help: "UK tax on buying UK shares (not CFDs)." },
  { key: "financing_pct_year", label: "Overnight financing", unit: "% a year", help: "CFDs and spread bets charge interest for each night a trade is open." },
];
const FORM_KEY = "gt.backtest.v1";

interface Form {
  symbol: string;
  timeframe: string;
  strategy: string;
  params: Record<string, Record<string, number>>; // per strategy
  start_balance: number;
  risk_pct: number;
  mode: "" | "cash" | "cfd";
  direction: "long" | "both";
  years: number;
  daily_loss_pct: number;
  max_drawdown_pct: number;
  costs: Partial<CostSettings>;
}

const DEFAULT_FORM: Form = {
  symbol: "EUR_USD", timeframe: "1d", strategy: "ma_cross", params: {}, start_balance: 200, risk_pct: 1, mode: "",
  direction: "long", years: 0, daily_loss_pct: 3, max_drawdown_pct: 20, costs: {},
};

export interface BacktestInit {
  symbol?: string;
  strategy?: string;
  timeframe?: string;
  direction?: string;
  mode?: "cash" | "cfd";
  years?: number;
}

function loadForm(initial?: BacktestInit): Form {
  let saved: Partial<Form> = {};
  try {
    saved = JSON.parse(localStorage.getItem(FORM_KEY) || "{}");
  } catch {
    /* ignore */
  }
  const picked: Partial<Form> = Object.fromEntries(Object.entries(initial ?? {}).filter(([, v]) => v !== undefined && v !== "")) as Partial<Form>;
  const form = { ...DEFAULT_FORM, ...saved, ...picked, ...(picked.symbol ? { mode: picked.mode ?? ("" as const), costs: {} } : {}) };
  // Arriving from Research: the strategy's default settings, as scanned.
  if (initial?.direction && initial.strategy) form.params = { ...form.params, [initial.strategy]: {} };
  return form;
}

export const money = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "–" : `${v < 0 ? "-" : ""}£${Math.abs(v).toLocaleString("en-GB", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
const pct = (v: number | null | undefined, sign = true) =>
  v === null || v === undefined ? "–" : `${sign && v > 0 ? "+" : ""}${v.toFixed(1)}%`;
const date = (t: number) => new Date(t * 1000).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
const price = (v: number, p: number) => v.toFixed(Math.min(6, Math.max(p, 2)));

interface Props {
  catalogue: Catalogue | null;
  favourites: SymbolInfo[];
  onToggleFavourite: (s: SymbolInfo, on: boolean) => void;
  onAuthError: (err: unknown) => void;
  initial?: BacktestInit;
  onRunOnPaper?: (p: AutoPrefill) => void;
}

export default function BacktestPage({ catalogue, favourites, onToggleFavourite, onAuthError, initial, onRunOnPaper }: Props) {
  const [info, setInfo] = useState<StrategiesResponse | null>(null);
  const [form, setForm] = useState<Form>(() => loadForm(initial));
  const [symbolInfo, setSymbolInfo] = useState<SymbolInfo | undefined>();
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [runs, setRuns] = useState<BacktestSummary[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCosts, setShowCosts] = useState(false);
  const [chart, setChart] = useState<ChartData | null>(null);
  const [focus, setFocus] = useState<number | undefined>();

  useEffect(() => {
    api.strategies().then(setInfo).catch(onAuthError);
    api.backtests().then((r) => setRuns(r.runs)).catch(onAuthError);
  }, [onAuthError]);

  useEffect(() => {
    try {
      localStorage.setItem(FORM_KEY, JSON.stringify(form));
    } catch {
      /* ignore */
    }
  }, [form]);

  // Work out the selected market's details (asset class decides default costs and leverage).
  useEffect(() => {
    if (symbolInfo?.code === form.symbol) return;
    const known = [...(catalogue?.symbols ?? []), ...favourites].find((s) => s.code === form.symbol);
    if (known) setSymbolInfo(known);
    else api.searchMarkets(form.symbol, "").then((r) => setSymbolInfo(r.results.find((s) => s.code === form.symbol))).catch(() => undefined);
  }, [form.symbol, catalogue, favourites, symbolInfo]);

  const strategy = info?.strategies.find((s) => s.key === form.strategy);
  const assetClass = symbolInfo?.asset_class ?? "forex";
  const mode: "cash" | "cfd" = form.mode || info?.defaultModes[assetClass] || "cfd";
  const defaults = info?.defaultCosts[assetClass]?.[mode];
  const params = form.params[form.strategy] ?? {};
  const update = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));
  // Arriving with a scalping strategy on a long timeframe (e.g. from Learn): use the one it's built for.
  useEffect(() => {
    if (strategy?.intradayOnly && !["1m", "5m", "15m"].includes(form.timeframe)) {
      setForm((f) => ({ ...f, timeframe: strategy.suggestedTimeframe || "5m" }));
    }
  }, [strategy, form.timeframe]);

  const [keepGoing, setKeepGoing] = useState(false);

  const run = useCallback(() => {
    if (!strategy) return;
    setRunning(true);
    setError(null);
    const body: BacktestRequest = {
      symbol: form.symbol, timeframe: form.timeframe, strategy: form.strategy, params, start_balance: form.start_balance,
      risk_pct: form.risk_pct, mode, direction: form.direction, years: form.years, daily_loss_pct: form.daily_loss_pct,
      max_drawdown_pct: form.max_drawdown_pct, costs: form.costs, keep_going: keepGoing,
    };
    api
      .runBacktest(body)
      .then((r) => {
        setResult(r);
        setFocus(undefined);
        api.backtests().then((x) => setRuns(x.runs)).catch(() => undefined);
      })
      .catch((err) => {
        onAuthError(err);
        setError(err instanceof Error ? err.message : "The backtest failed.");
      })
      .finally(() => setRunning(false));
  }, [form, mode, params, strategy, onAuthError, keepGoing]);

  // Price chart for the result, with every trade marked on it.
  useEffect(() => {
    if (!result) return;
    setChart(null);
    api.chart(result.symbol.code, result.timeframe, "candles", [], false, 2000).then(setChart).catch(() => setChart(null));
  }, [result]);

  const markers: ChartMarker[] = useMemo(() => {
    if (!result) return [];
    const out: ChartMarker[] = [];
    for (const t of result.trades) {
      const long = t.side === "long";
      out.push({ time: t.entryTime as Time, position: long ? "belowBar" : "aboveBar", shape: long ? "arrowUp" : "arrowDown",
        color: long ? "#34d399" : "#f87171", text: long ? "Buy" : "Short" });
      out.push({ time: t.exitTime as Time, position: long ? "aboveBar" : "belowBar", shape: "circle",
        color: t.pnl >= 0 ? "#34d399" : "#f87171", text: money(t.pnl) });
    }
    return out;
  }, [result]);

  function openRun(id: number) {
    api.backtest(id).then((r) => {
      setResult(r);
      window.scrollTo({ top: 0, behavior: "smooth" });
    }).catch(onAuthError);
  }

  function removeRun(id: number) {
    api.deleteBacktest(id).then(() => setRuns((rs) => rs.filter((r) => r.id !== id))).catch(onAuthError);
  }

  const m = result?.metrics;
  const bh = result?.buyHold;

  return (
    <div className="page backtest">
      <aside className="bt-form" aria-label="Backtest settings">
        <h2>Backtest a strategy</h2>
        <p className="muted small-text">Replays the strategy over past prices with realistic costs and the risk guard switched on.</p>

        <MarketPicker
          value={form.symbol}
          current={symbolInfo}
          popular={catalogue?.symbols ?? []}
          counts={catalogue?.marketCounts ?? {}}
          favourites={favourites}
          onToggleFavourite={onToggleFavourite}
          onChange={(s) => {
            setSymbolInfo(s);
            update({ symbol: s.code, mode: "", costs: {} });
          }}
          onAuthError={onAuthError}
        />

        <div className="form-row">
          <span className="field-label">Timeframe</span>
          <div className="segmented" role="group" aria-label="Timeframe">
            {TIMEFRAMES.map((t) => (
              <button key={t} type="button" className={form.timeframe === t ? "on" : ""} onClick={() => update({ timeframe: t })}>{t}</button>
            ))}
          </div>
        </div>

        <label className="form-row">
          <span className="field-label">Strategy</span>
          <select value={form.strategy} onChange={(e) => {
            // Scalping strategies only work on short candles: switch to the one they're built for.
            const picked = info?.strategies.find((x) => x.key === e.target.value);
            const short = ["1m", "5m", "15m"].includes(form.timeframe);
            update(picked?.intradayOnly && !short ? { strategy: e.target.value, timeframe: picked.suggestedTimeframe || "5m" } : { strategy: e.target.value });
          }}>
            {info?.strategies.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
          </select>
        </label>
        {strategy && <p className="muted small-text">{strategy.summary}</p>}
        {strategy?.intradayOnly && (
          <p className="warn caution small-text">
            Scalping: short trades on {strategy.suggestedTimeframe || "5m"} candles, closed by the end of the session (UK time).
            Costs take a much bigger share of each trade than on daily charts, so read the costs line closely.
          </p>
        )}

        {strategy && strategy.params.length > 0 && (
          <div className="param-grid">
            {strategy.params.map((p) => (
              <label key={p.key} title={p.help}>
                <span>{p.label}</span>
                <input type="number" min={p.minimum} max={p.maximum} step={p.step}
                  value={params[p.key] ?? p.default}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    if (Number.isFinite(v)) update({ params: { ...form.params, [form.strategy]: { ...params, [p.key]: v } } });
                  }} />
              </label>
            ))}
          </div>
        )}

        <fieldset className="form-group">
          <legend>Account</legend>
          <div className="param-grid">
            <label>
              <span>Starting balance (£)</span>
              <input type="number" min={10} step="any" value={form.start_balance}
                onChange={(e) => update({ start_balance: Number(e.target.value) || 200 })} />
            </label>
            <label title="How much of the account each trade risks if its stop-loss is hit. The guard allows up to 2%.">
              <span>Risk per trade (%)</span>
              <input type="number" min={0.1} max={2} step="any" value={form.risk_pct}
                onChange={(e) => update({ risk_pct: Math.min(2, Math.max(0.1, Number(e.target.value) || 1)) })} />
            </label>
          </div>
          <div className="segmented wide" role="radiogroup" aria-label="Account type">
            <button type="button" className={mode === "cash" ? "on" : ""} onClick={() => update({ mode: "cash", direction: "long", costs: {} })}
              title="Buy the real thing with your own money. No leverage, no shorting.">Real shares / no leverage</button>
            <button type="button" className={mode === "cfd" ? "on" : ""} onClick={() => update({ mode: "cfd", costs: {} })}
              title="CFD or spread bet: leverage allowed up to UK retail limits, overnight financing charged.">CFD / spread bet</button>
          </div>
          {mode === "cfd" && strategy?.canShort && (
            <label className="check-row">
              <input type="checkbox" checked={form.direction === "both"} onChange={(e) => update({ direction: e.target.checked ? "both" : "long" })} />
              Also take short trades (betting on falls)
            </label>
          )}
        </fieldset>

        <div className="form-row">
          <span className="field-label">History to test</span>
          <div className="segmented" role="group" aria-label="History">
            {YEARS.map((y) => (
              <button key={y.v} type="button" className={form.years === y.v ? "on" : ""} onClick={() => update({ years: y.v })}>{y.label}</button>
            ))}
          </div>
        </div>
        <label className="check-row" title="Tests only. Paper and live accounts always stop at the drawdown limit.">
          <input type="checkbox" checked={keepGoing} onChange={(e) => setKeepGoing(e.target.checked)} />
          Keep testing past the drawdown limit
        </label>
        {keepGoing && <p className="muted small-text">Shows what happened after the account fell to its drawdown limit, which
          would have stopped trading for real. Paper and live accounts always stop there.</p>}

        <button type="button" className="link-button" onClick={() => setShowCosts((s) => !s)} aria-expanded={showCosts}>
          {showCosts ? "▾" : "▸"} Costs and risk limits
        </button>
        {showCosts && defaults && (
          <div className="form-group">
            <div className="param-grid">
              {COST_FIELDS.map((f) => (
                <label key={f.key} title={f.help}>
                  <span>{f.label} ({f.unit})</span>
                  <input type="number" min={0} step={f.key === "commission_gbp" ? 0.5 : 0.01}
                    value={form.costs[f.key] ?? defaults[f.key]}
                    onChange={(e) => update({ costs: { ...form.costs, [f.key]: Number(e.target.value) } })} />
                </label>
              ))}
              <label title="After losing this much in a day, no new trades until tomorrow.">
                <span>Daily loss limit (%)</span>
                <input type="number" min={0.5} max={20} step={0.5} value={form.daily_loss_pct}
                  onChange={(e) => update({ daily_loss_pct: Number(e.target.value) || 3 })} />
              </label>
              <label title="After falling this far from its high, the account stops trading.">
                <span>Drawdown limit (%)</span>
                <input type="number" min={2} max={60} step={1} value={form.max_drawdown_pct}
                  onChange={(e) => update({ max_drawdown_pct: Number(e.target.value) || 20 })} />
              </label>
            </div>
            <button type="button" className="ghost small" onClick={() => update({ costs: {}, daily_loss_pct: 3, max_drawdown_pct: 20 })}>
              Reset to typical UK costs
            </button>
          </div>
        )}

        <button type="button" className="primary" onClick={run} disabled={running || !strategy}>
          {running ? "Running… (first run downloads history)" : "Run backtest"}
        </button>
        {error && <p className="form-error" role="alert">{error}</p>}

        {runs.length > 0 && (
          <div className="past-runs">
            <h3>Past runs</h3>
            <ul>
              {runs.slice(0, 30).map((r) => (
                <li key={r.id} className={result?.id === r.id ? "current" : ""}>
                  <button type="button" className="run-open" onClick={() => openRun(r.id)}>
                    <span className="run-title">{r.strategyName}</span>
                    <span className="muted">{displayCode(r.symbol)} · {r.timeframe}{r.sample ? " · sample" : ""}</span>
                    <span className={r.returnPct >= 0 ? "up" : "down"}>{pct(r.returnPct)}</span>
                  </button>
                  <button type="button" className="ghost icon" aria-label={`Delete this ${r.strategyName} run`} onClick={() => removeRun(r.id)}>×</button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </aside>

      <section className="bt-results" aria-live="polite">
        {!result && !running && (
          <div className="empty-state">
            <h2>No results yet</h2>
            <p className="muted">Pick a market and a strategy, then press <b>Run backtest</b>. Every result includes trading costs and is compared with simply buying and holding.</p>
          </div>
        )}
        {running && !result && <div className="empty-state"><p className="muted">Running the backtest…</p></div>}

        {result && m && bh && (
          <>
            <header className="result-head">
              <h2>{result.strategy.name} · {displayCode(result.symbol.code)} <span className="muted">{result.symbol.name} · {result.timeframe}</span></h2>
              <p className="muted small-text">{date(result.from)} to {date(result.to)} · {result.candles.toLocaleString("en-GB")} candles · {result.assumptions.modeLabel}</p>
              <p className="headline">{result.headline}</p>
              {onRunOnPaper && !result.sample && !["buy_hold", "support_resistance"].includes(result.strategy.key) && (
                <button type="button" className="small" title="Let these rules trade a paper account on live prices, to see if the backtest holds up"
                  onClick={() => onRunOnPaper({ symbol: result.symbol.code, timeframe: result.timeframe, strategy: result.strategy.key,
                    params: result.strategy.params as Record<string, number>, direction: result.assumptions.direction })}>
                  Run these rules automatically on paper
                </button>
              )}
            </header>

            {result.warnings.length > 0 && (
              <ul className="warnings">
                {result.warnings.map((w, i) => <li key={i} className={`warn ${w.level}`}>{w.text}</li>)}
              </ul>
            )}

            <div className="stats">
              <Stat label="Final balance" value={money(m.final)} sub={`from ${money(m.start, 0)}`} />
              <Stat label="Return" value={pct(m.returnPct)} tone={m.returnPct} sub={`Buy and hold ${pct(bh.returnPct)}`} />
              <Stat label="Per year" value={pct(m.annualPct)} tone={m.annualPct ?? 0} sub={`Buy and hold ${pct(bh.annualPct)}`} />
              <Stat label="Trades" value={String(m.trades)} sub={m.winRate === null ? "" : `${m.winRate.toFixed(0)}% winners`} />
              <Stat label="Average win / loss" value={`${money(m.avgWin)} / ${money(m.avgLoss)}`} sub={m.profitFactor ? `Profit factor ${m.profitFactor.toFixed(2)}` : ""} />
              <Stat label="Worst fall (drawdown)" value={`-${m.maxDrawdownPct.toFixed(1)}%`} sub={`Buy and hold -${bh.maxDrawdownPct.toFixed(1)}%`} />
              <Stat label="Costs paid" value={money(m.costs)} sub={`Before costs ${money(m.grossNet)}`} />
              <Stat label="Longest losing run" value={`${m.longestLosingRun} trades`} sub={m.avgR === null ? "" : `Average ${m.avgR.toFixed(2)}R per trade`} />
            </div>

            <div className="card">
              <h3>Account balance <span className="legend-key strat">Strategy</span> <span className="legend-key bh">Buy and hold</span></h3>
              <EquityChart strategy={result.equity} buyHold={result.buyHoldEquity} start={result.startBalance}
                limitHit={result.limitHit} keptGoing={result.keptGoing} />
            </div>
            <MonteCarloCard mc={result.monteCarlo} />

            <div className="card chart-card">
              <h3>Trades on the chart <span className="muted small">(latest 2,000 candles; click a trade below to jump to it)</span></h3>
              <div className="bt-chart">
                {chart ? <ChartView data={chart} markers={markers} focusTime={focus} /> : <div className="splash">Loading chart…</div>}
              </div>
            </div>

            <div className="card">
              <h3>Every trade ({result.trades.length})</h3>
              {result.trades.length === 0 ? <p className="muted">No trades.</p> : (
                <div className="table-wrap">
                  <table className="trades">
                    <thead>
                      <tr>
                        <th>#</th><th>Side</th><th>Entry</th><th>Price</th><th>Stop</th><th>Exit</th><th>Price</th>
                        <th>Why it closed</th><th className="num">Profit</th><th className="num">R</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.trades.map((t, i) => (
                        <tr key={i} onClick={() => setFocus(t.entryTime)} className="clickable">
                          <td>{i + 1}</td>
                          <td>{t.side === "long" ? "Buy" : "Short"}</td>
                          <td>{date(t.entryTime)}</td>
                          <td className="mono">{price(t.entryPrice, result.symbol.precision)}</td>
                          <td className="mono">{t.stop ? price(t.stop, result.symbol.precision) : "–"}</td>
                          <td>{date(t.exitTime)}</td>
                          <td className="mono">{price(t.exitPrice, result.symbol.precision)}</td>
                          <td>{t.exitReason}{t.note ? ` · ${t.note}` : ""}</td>
                          <td className={`num ${t.pnl >= 0 ? "up" : "down"}`}>{money(t.pnl)}</td>
                          <td className="num">{t.r === null ? "–" : t.r.toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="muted small-text">R = profit divided by the amount risked. +2R means twice what was risked was won; -1R is a normal stop-loss.</p>
            </div>

            <div className="card assumptions">
              <h3>How this was tested</h3>
              <ul>
                <li>{result.assumptions.modeLabel}; leverage capped at {result.assumptions.leverageCap}:1. {result.assumptions.direction === "both" ? "Long and short trades." : "Long trades only."}</li>
                <li>Risk {result.assumptions.riskPct}% per trade; daily loss limit {result.assumptions.dailyLossPct}%; trading stops after a {result.assumptions.maxDrawdownPct}% fall.</li>
                <li>Costs: spread {result.assumptions.costs.spread_pct}%, slippage {result.assumptions.costs.slippage_pct}%, commission {money(result.assumptions.costs.commission_gbp)} per order
                  {result.assumptions.costs.fx_fee_pct ? `, currency fee ${result.assumptions.costs.fx_fee_pct}%` : ""}
                  {result.assumptions.costs.stamp_duty_pct && result.assumptions.mode === "cash" ? `, stamp duty ${result.assumptions.costs.stamp_duty_pct}%` : ""}
                  {result.assumptions.costs.financing_pct_year && result.assumptions.mode === "cfd" ? `, overnight financing ${result.assumptions.costs.financing_pct_year}% a year` : ""}.</li>
                <li>{result.assumptions.fills}</li>
                <li>Prices from {result.sample ? "made-up sample data" : result.source === "oanda" ? "the OANDA demo feed" : result.source === "twelvedata" ? "Twelve Data" : "Alpha Vantage"}; quoted in {result.assumptions.currency === "GBX" ? "pence" : result.assumptions.currency}, reported in pounds.</li>
                <li>Past results don't predict future ones. This is a test, not a recommendation.</li>
              </ul>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: number }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className={`stat-value ${tone === undefined ? "" : tone >= 0 ? "up" : "down"}`}>{value}</span>
      {sub && <span className="stat-sub muted">{sub}</span>}
    </div>
  );
}
