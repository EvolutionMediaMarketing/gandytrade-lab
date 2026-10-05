import { useEffect, useState } from "react";
import { api } from "./api";
import { money } from "./BacktestPage";
import EquityChart from "./EquityChart";
import MarketPicker, { displayCode } from "./MarketPicker";
import type { BasketInit, BasketResult, Catalogue, StrategiesResponse, SymbolInfo } from "./types";

const TIMEFRAMES = ["15m", "1h", "4h", "1d", "1w"];
const YEARS = [{ v: 0, label: "All" }, { v: 3, label: "3 yrs" }, { v: 5, label: "5 yrs" }, { v: 10, label: "10 yrs" }];
const DEFAULT_MARKETS = ["XAU_USD", "XAG_USD", "BCO_USD", "CORN_USD", "NAS100_USD", "JP225_USD"];
const pct = (v: number | null | undefined, sign = true) =>
  v === null || v === undefined ? "–" : `${sign && v > 0 ? "+" : ""}${v.toFixed(1)}%`;

interface Props {
  catalogue: Catalogue | null;
  favourites: SymbolInfo[];
  onToggleFavourite: (s: SymbolInfo, on: boolean) => void;
  onAuthError: (err: unknown) => void;
  initial?: BasketInit | null;
}

/** One strategy on several markets at once, sharing one account and its safeguards. */
export default function BasketPanel({ catalogue, favourites, onToggleFavourite, onAuthError, initial }: Props) {
  const [info, setInfo] = useState<StrategiesResponse | null>(null);
  const [markets, setMarkets] = useState<string[]>(initial?.markets?.length ? initial.markets : DEFAULT_MARKETS);
  const [adding, setAdding] = useState("EUR_USD");
  const [strategy, setStrategy] = useState(initial?.strategy ?? "breakout");
  const [timeframe, setTimeframe] = useState(initial?.timeframe ?? "1d");
  const [direction, setDirection] = useState(initial?.direction === "both" ? "both" : "long");
  const [balance, setBalance] = useState(200);
  const [risk, setRisk] = useState(1);
  const [openRisk, setOpenRisk] = useState(10);
  const [years, setYears] = useState(0);
  const [result, setResult] = useState<BasketResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.strategies().then(setInfo).catch(onAuthError); }, [onAuthError]);
  const chosen = info?.strategies.find((s) => s.key === strategy);
  const known = [...(catalogue?.symbols ?? []), ...favourites];
  const nameOf = (code: string) => known.find((s) => s.code === code)?.name ?? "";

  function run() {
    setRunning(true);
    setError(null);
    api.runBasket({ markets, timeframe, strategy, direction, start_balance: balance, risk_pct: risk, max_open_risk_pct: openRisk, years, mode: "cfd" })
      .then(setResult)
      .catch((err) => { onAuthError(err); setError(err instanceof Error ? err.message : "The basket test didn't run."); })
      .finally(() => setRunning(false));
  }

  const m = result?.metrics;
  return (
    <div className="page backtest">
      <aside className="bt-form" aria-label="Basket settings">
        <h2>Backtest a basket</h2>
        <p className="muted small-text">One strategy on several markets at once, sharing one CFD account: 1% risk a trade, and the open-risk limit across them all.</p>

        <div className="form-row">
          <span className="field-label">Markets ({markets.length})</span>
          <div className="chips">
            {markets.map((code) => (
              <button key={code} type="button" className="chip on" title={`${nameOf(code)} · click to remove`}
                onClick={() => setMarkets(markets.filter((c) => c !== code))}>
                {displayCode(code)} ×
              </button>
            ))}
          </div>
        </div>
        <MarketPicker value={adding} current={known.find((s) => s.code === adding)} popular={catalogue?.symbols ?? []}
          counts={catalogue?.marketCounts ?? {}} favourites={favourites} onToggleFavourite={onToggleFavourite} onAuthError={onAuthError}
          onChange={(s) => { setAdding(s.code); if (!markets.includes(s.code) && markets.length < 12) setMarkets([...markets, s.code]); }} />
        <span className="muted small-text">Pick a market above to add it (up to 12).</span>

        <div className="form-row">
          <span className="field-label">Timeframe</span>
          <div className="segmented" role="group" aria-label="Timeframe">
            {TIMEFRAMES.map((t) => <button key={t} type="button" className={timeframe === t ? "on" : ""} onClick={() => setTimeframe(t)}>{t}</button>)}
          </div>
        </div>
        <label className="form-row">
          <span className="field-label">Strategy</span>
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
            {info?.strategies.filter((s) => !s.benchmark && s.key !== "support_resistance").map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
          </select>
        </label>
        {chosen && <p className="muted small-text">{chosen.summary}</p>}
        {chosen?.canShort && (
          <div className="segmented wide">
            <button type="button" className={direction === "long" ? "on" : ""} onClick={() => setDirection("long")}>Buys only</button>
            <button type="button" className={direction === "both" ? "on" : ""} onClick={() => setDirection("both")}>Buys and shorts</button>
          </div>
        )}
        <div className="param-grid">
          <label><span>Starting balance (£)</span><input type="number" min={10} step="any" value={balance} onChange={(e) => setBalance(Number(e.target.value) || 200)} /></label>
          <label><span>Risk per trade (%)</span><input type="number" min={0.1} max={2} step={0.1} value={risk} onChange={(e) => setRisk(Number(e.target.value) || 1)} /></label>
          <label title="If every open trade hit its stop-loss together, the most the account could lose"><span>Most at risk at once (%)</span>
            <input type="number" min={1} max={10} step={0.5} value={openRisk} onChange={(e) => setOpenRisk(Number(e.target.value) || 10)} /></label>
        </div>
        <div className="form-row">
          <span className="field-label">History to test</span>
          <div className="segmented">
            {YEARS.map((y) => <button key={y.v} type="button" className={years === y.v ? "on" : ""} onClick={() => setYears(y.v)}>{y.label}</button>)}
          </div>
          <span className="muted small-text">Only the period every market has prices for is used.</span>
        </div>
        {error && <p className="form-error">{error}</p>}
        <button type="button" className="primary" disabled={running || markets.length < 2} onClick={run}>{running ? "Running…" : "Run basket backtest"}</button>
      </aside>

      <section className="bt-results">
        {!result && !running && (
          <div className="empty-state">
            <h2>No basket results yet</h2>
            <p className="muted">A rule that works on one market often has a few trades a year there. Running it on several markets at once
              gives it more chances, and losses in one place are often covered by a trend somewhere else. This shows the real combined
              result, with the safeguards working across the whole basket.</p>
          </div>
        )}
        {running && <div className="empty-state"><p className="muted">Running the basket… the first run on new markets downloads their history.</p></div>}
        {result && m && (
          <>
            <header className="result-head">
              <h2>{result.strategy.name} · {result.markets.length} markets <span className="muted">{result.timeframe} · {result.direction === "both" ? "buys and shorts" : "buys only"}</span></h2>
              <p className="muted small-text">
                {new Date(result.from * 1000).toLocaleDateString("en-GB", { month: "short", year: "numeric" })} to{" "}
                {new Date(result.to * 1000).toLocaleDateString("en-GB", { month: "short", year: "numeric" })} · {result.riskPct}% a trade ·
                at most {result.maxOpenRiskPct}% at risk at once
              </p>
              <p className="headline">{result.headline}</p>
            </header>
            {result.warnings.length > 0 && (
              <ul className="warnings">{result.warnings.map((w, i) => <li key={i} className={`warn ${w.level}`}>{w.text}</li>)}</ul>
            )}
            <div className="stats">
              <Stat label="Final balance" value={money(m.final)} sub={`from ${money(m.start, 0)}`} />
              <Stat label="Return" value={pct(m.returnPct)} tone={m.returnPct} sub={`Holding the basket ${pct(result.buyHold.returnPct)}`} />
              <Stat label="Per year" value={pct(m.annualPct)} tone={m.annualPct ?? 0} sub={`Each market alone averaged ${pct(result.averageAloneReturnPct)} in total`} />
              <Stat label="Trades" value={String(m.trades)} sub={`${pct(m.winRate, false)} winners · average ${m.avgR ?? "–"}R`} />
              <Stat label="Worst fall" value={pct(-m.maxDrawdownPct, false)} sub={`Holding the basket ${pct(-result.buyHold.maxDrawdownPct, false)}`} />
              <Stat label="Costs paid" value={money(m.costs)} sub={`Before costs ${money(m.grossNet)}`} />
              <Stat label="Longest losing run" value={`${m.longestLosingRun} trades`} />
              <Stat label="Profit factor" value={m.profitFactor === null ? "–" : String(m.profitFactor)} sub="Money won ÷ money lost" />
            </div>
            <div className="card">
              <h3>Account balance <span className="muted small-text">— basket · grey: holding the basket</span></h3>
              <EquityChart strategy={result.equity} buyHold={result.buyHoldEquity} start={result.startBalance} label="Basket" />
            </div>
            <div className="card">
              <h3>Each market</h3>
              <div className="table-wrap">
                <table className="trades">
                  <thead>
                    <tr><th>Market</th><th className="num">Trades in basket</th><th className="num">Net in basket</th><th className="num">Win rate</th>
                      <th className="num">Avg R</th><th className="num">Traded alone</th><th className="num">Held alone</th></tr>
                  </thead>
                  <tbody>
                    {result.markets.map((r) => (
                      <tr key={r.market}>
                        <td>{displayCode(r.market)} <span className="muted">{r.name}</span></td>
                        <td className="num">{r.basketTrades}</td>
                        <td className={`num ${r.basketNet >= 0 ? "up" : "down"}`}>{money(r.basketNet)}</td>
                        <td className="num">{pct(r.basketWinRate, false)}</td>
                        <td className="num">{r.basketAvgR ?? "–"}</td>
                        <td className={`num ${r.aloneReturnPct >= 0 ? "up" : "down"}`}>{pct(r.aloneReturnPct)}</td>
                        <td className="num muted">{pct(r.holdReturnPct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted small-text">"Traded alone" is the same rules on that market with the whole balance, as on the normal Backtest page.</p>
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
