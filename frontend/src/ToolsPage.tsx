import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { money } from "./BacktestPage";
import MarketPicker, { displayCode } from "./MarketPicker";
import type { BacktestSummary, Catalogue, PositionSize, Quote, SymbolInfo } from "./types";

interface Props {
  catalogue: Catalogue | null;
  favourites: SymbolInfo[];
  onToggleFavourite: (s: SymbolInfo, on: boolean) => void;
  onAuthError: (err: unknown) => void;
}

const num = (v: string, fallback = 0) => (Number.isFinite(Number(v)) && v !== "" ? Number(v) : fallback);

export default function ToolsPage(props: Props) {
  return (
    <div className="page tools">
      <PositionCalculator {...props} />
      <GoalCalculator onAuthError={props.onAuthError} />
    </div>
  );
}

function PositionCalculator({ catalogue, favourites, onToggleFavourite, onAuthError }: Props) {
  const [symbol, setSymbol] = useState<SymbolInfo | undefined>();
  const [code, setCode] = useState("GBP_USD");
  const [mode, setMode] = useState<"" | "cash" | "cfd">("");
  const [balance, setBalance] = useState("200");
  const [risk, setRisk] = useState("1");
  const [entry, setEntry] = useState("");
  const [stop, setStop] = useState("");
  const [out, setOut] = useState<PositionSize | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  // The entry box follows the live price until you type your own number in it.
  const entryIsAuto = useRef(true);

  useEffect(() => {
    if (!symbol) setSymbol(catalogue?.symbols.find((s) => s.code === code));
  }, [catalogue, code, symbol]);

  useEffect(() => {
    let cancelled = false;
    setQuote(null);
    api
      .quote(code)
      .then((q) => {
        if (cancelled) return;
        setQuote(q);
        if (entryIsAuto.current) setEntry(q.price.toFixed(q.symbol.precision));
      })
      .catch(onAuthError);
    return () => {
      cancelled = true;
    };
  }, [code, onAuthError]);

  const decimals = quote?.symbol.precision ?? symbol?.precision ?? 2;
  const shown = (v: number) => v.toFixed(decimals);
  const quoteTime = quote ? new Date(quote.time * 1000).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
  const shortAllowed = (mode || (["stock", "etf", "ukstock"].includes(symbol?.asset_class ?? "") ? "cash" : "cfd")) === "cfd";

  function calculate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    api
      .positionSize({ symbol: code, balance: num(balance, 200), risk_pct: num(risk, 1), entry: num(entry), stop: num(stop), mode })
      .then(setOut)
      .catch((err) => {
        onAuthError(err);
        setOut(null);
        setError(err instanceof Error ? err.message : "Couldn't work that out.");
      });
  }

  const unitWord = out?.symbol.asset_class === "forex" ? `units of ${out.symbol.code.split("_")[0]}` : ["stock", "etf", "ukstock"].includes(out?.symbol.asset_class ?? "") ? "shares" : "units";
  const priceHint = symbol?.asset_class === "ukstock" ? "in pence" : symbol?.asset_class === "stock" || symbol?.asset_class === "etf" ? "in US dollars" : "as shown on the chart";

  return (
    <section className="card tool">
      <h2>Position size</h2>
      <p className="muted small-text">How big a trade should be so that, if the stop-loss is hit, you lose only the amount you chose. Uses the same risk guard as the backtester.</p>
      <form onSubmit={calculate} className="tool-form">
        <MarketPicker value={code} current={symbol} popular={catalogue?.symbols ?? []} counts={catalogue?.marketCounts ?? {}}
          favourites={favourites} onToggleFavourite={onToggleFavourite}
          onChange={(s) => { setSymbol(s); setCode(s.code); setOut(null); setMode(""); entryIsAuto.current = true; setEntry(""); setStop(""); }} onAuthError={onAuthError} />
        <div className="segmented wide" role="radiogroup" aria-label="Account type">
          <button type="button" className={mode === "cash" ? "on" : ""} onClick={() => setMode("cash")}>Real shares / no leverage</button>
          <button type="button" className={mode === "cfd" ? "on" : ""} onClick={() => setMode("cfd")}>CFD / spread bet</button>
          <button type="button" className={mode === "" ? "on" : ""} onClick={() => setMode("")}>Usual for this market</button>
        </div>
        <div className="param-grid">
          <label><span>Account balance (£)</span><input type="number" min={1} step="any" value={balance} onChange={(e) => setBalance(e.target.value)} /></label>
          <label><span>Risk per trade (%)</span><input type="number" min={0.1} max={2} step="any" value={risk} onChange={(e) => setRisk(e.target.value)} /></label>
          <label><span>Entry price ({priceHint})</span>
            <input type="number" step="any" required value={entry} onChange={(e) => { entryIsAuto.current = false; setEntry(e.target.value); }} /></label>
          <label><span>Stop-loss price</span><input type="number" step="any" required value={stop} onChange={(e) => setStop(e.target.value)} /></label>
        </div>
        {quote && (
          <div className="quote-hints">
            <p>
              Latest price <b className="mono">{shown(quote.price)}</b> <span className="muted">({quoteTime}{quote.sample ? ", sample data" : ""})</span>
              {entry !== shown(quote.price) && (
                <button type="button" className="link-button" onClick={() => { entryIsAuto.current = true; setEntry(shown(quote.price)); }}>Use it</button>
              )}
            </p>
            {quote.suggestedStopLong !== null && quote.dailyAtr !== null && (
              <p>
                A typical day's move (ATR) is {shown(quote.dailyAtr)}. A stop 2 × that away:{" "}
                <button type="button" className="link-button" onClick={() => setStop(shown(quote.suggestedStopLong!))}>
                  {shown(quote.suggestedStopLong)} for a buy
                </button>
                {shortAllowed && quote.suggestedStopShort !== null && (
                  <> or <button type="button" className="link-button" onClick={() => setStop(shown(quote.suggestedStopShort!))}>
                    {shown(quote.suggestedStopShort)} for a short
                  </button></>
                )}
              </p>
            )}
            <p className="muted">A guide only: the price will have moved by the time you'd trade.</p>
          </div>
        )}
        <button className="primary" type="submit">Work it out</button>
        {error && <p className="form-error" role="alert">{error}</p>}
      </form>

      {out && (
        <div className="tool-result">
          <p className="big">
            {out.side === "long" ? "Buy" : "Sell short"} <b>{out.units < 10 ? out.units.toFixed(4) : Math.floor(out.units).toLocaleString("en-GB")}</b> {unitWord}{out.symbol.asset_class === "forex" ? "" : ` of ${displayCode(out.symbol.code)}`}
          </p>
          <dl className="facts">
            <dt>If the stop is hit you lose about</dt><dd>{money(out.riskGbp)}</dd>
            <dt>Position value</dt><dd>{money(out.valueGbp)} ({out.leverageUsed.toFixed(2)}× your balance)</dd>
            {out.marginGbp !== null && <><dt>Margin the broker holds</dt><dd>{money(out.marginGbp)} (at {out.leverageCap}:1)</dd></>}
            <dt>{moveLabel(out)}</dt><dd>{money(out.perPointGbp * moveStep(out), out.perPointGbp * moveStep(out) < 1 ? 3 : 2)}</dd>
            <dt>Typical cost to open and close</dt><dd>{money(out.costGbp)}</dd>
          </dl>
          {out.capped && <p className="warn caution">{out.note}</p>}
          {out.rateNote && <p className="muted small-text">{out.rateNote}</p>}
          {out.symbol.asset_class === "ukstock" && <p className="muted small-text">Many UK platforms only sell whole shares: round down.</p>}
        </div>
      )}
    </section>
  );
}

/** The price move people quote for each kind of market: a pip for currencies, 1p or $1 for shares. */
function moveStep(out: PositionSize): number {
  if (out.symbol.asset_class === "forex") return out.symbol.code.includes("JPY") ? 0.01 : 0.0001;
  return 1;
}

function moveLabel(out: PositionSize): string {
  if (out.symbol.asset_class === "forex") return `Each pip (${moveStep(out)}) is worth`;
  if (out.currency === "GBX") return "Each 1p move is worth";
  if (out.currency === "USD" && ["stock", "etf"].includes(out.symbol.asset_class)) return "Each $1 move is worth";
  return "Each 1-point move is worth";
}

function GoalCalculator({ onAuthError }: { onAuthError: (err: unknown) => void }) {
  const [target, setTarget] = useState("500");
  const [have, setHave] = useState("200");
  const [topUp, setTopUp] = useState("50");
  const [expected, setExpected] = useState("7");
  const [runs, setRuns] = useState<BacktestSummary[]>([]);

  useEffect(() => {
    api.backtests().then((r) => setRuns(r.runs)).catch(onAuthError);
  }, [onAuthError]);

  const calc = useMemo(() => {
    const t = num(target), h = Math.max(1, num(have, 1)), top = Math.max(0, num(topUp)), r = Math.max(0.1, num(expected, 7)) / 100;
    const monthlyNeeded = t / h;
    const yearlyNeeded = (Math.pow(1 + monthlyNeeded, 12) - 1) * 100;
    const pot = (t * 12) / r;
    let balance = h, months = 0;
    const monthly = Math.pow(1 + r, 1 / 12) - 1;
    while (balance < pot && months < 1200) {
      balance = balance * (1 + monthly) + top;
      months++;
    }
    const verdict = yearlyNeeded <= 10 ? "realistic" : yearlyNeeded <= 25 ? "ambitious" : "unrealistic";
    return { monthlyNeeded: monthlyNeeded * 100, yearlyNeeded, pot, months, verdict, r: r * 100 };
  }, [target, have, topUp, expected]);

  const best = runs
    .filter((r) => !r.sample && r.trades >= 30 && r.annualPct !== null && r.strategy !== "buy_hold")
    .sort((a, b) => (b.annualPct ?? 0) - (a.annualPct ?? 0))[0];

  const yearsText = calc.months >= 1200 ? "more than 100 years" : calc.months < 12 ? `${calc.months} months` : `about ${(calc.months / 12).toFixed(1)} years`;
  const bigPct = (v: number) => (v > 10000 ? "over 10,000%" : `${v.toLocaleString("en-GB", { maximumFractionDigits: 1 })}%`);

  return (
    <section className="card tool">
      <h2>Income goal</h2>
      <p className="muted small-text">What return your goal needs, how realistic that is, and a steadier route to it.</p>
      <div className="param-grid">
        <label><span>Monthly income goal (£)</span><input type="number" min={0} step="any" value={target} onChange={(e) => setTarget(e.target.value)} /></label>
        <label><span>Money you have now (£)</span><input type="number" min={1} step="any" value={have} onChange={(e) => setHave(e.target.value)} /></label>
        <label><span>You add each month (£)</span><input type="number" min={0} step="any" value={topUp} onChange={(e) => setTopUp(e.target.value)} /></label>
        <label title="Broad share indices have averaged roughly 5–10% a year over the long run, with big ups and downs."><span>Expected return a year (%)</span><input type="number" min={0.1} max={50} step="any" value={expected} onChange={(e) => setExpected(e.target.value)} /></label>
      </div>

      <div className="tool-result">
        <p className="big">
          {money(num(target), 0)} a month from {money(num(have), 0)} needs <b>{bigPct(calc.monthlyNeeded)} a month</b>
          {calc.yearlyNeeded < 1e7 && <> (<b>{bigPct(calc.yearlyNeeded)} a year</b>)</>}.
        </p>
        <p className={`verdict ${calc.verdict}`}>
          {calc.verdict === "realistic" && "Realistic: in line with long-run returns from broad share markets."}
          {calc.verdict === "ambitious" && "Very ambitious: even top professional funds rarely keep this up for years."}
          {calc.verdict === "unrealistic" && "Not realistic from this starting amount. Chasing it means taking risks that usually empty the account. The steadier route is below."}
        </p>
        <dl className="facts">
          <dt>Pot needed to draw {money(num(target), 0)} a month at {calc.r.toFixed(1)}% a year</dt><dd>{money(calc.pot, 0)}</dd>
          <dt>Time to build it, adding {money(num(topUp), 0)} a month</dt><dd>{yearsText}</dd>
          <dt>Your best backtest so far (real data, 30+ trades)</dt>
          <dd>{best ? `${best.annualPct?.toFixed(1)}% a year · ${best.strategyName} on ${displayCode(best.symbol)} ${best.timeframe}` : "None yet: run some backtests to compare"}</dd>
        </dl>
        <p className="muted small-text">Raising the monthly top-up shortens the time far more reliably than chasing a higher return. Figures ignore tax and inflation.</p>
      </div>
    </section>
  );
}
