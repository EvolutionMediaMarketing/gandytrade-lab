import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import MarketPicker, { displayCode } from "./MarketPicker";
import type { AutoOptions, AutoPrefill, AutoRun, Catalogue, PaperAccount, SymbolInfo } from "./types";

const JUDGE_AFTER = 30; // trades before paper results say much
const REFRESH_MS = 60_000;

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "–";
const num = (v: number | null | undefined, digits = 1, suffix = "") => (v === null || v === undefined ? "–" : `${v.toFixed(digits)}${suffix}`);

interface Props {
  account: PaperAccount;
  catalogue: Catalogue | null;
  favourites: SymbolInfo[];
  onToggleFavourite: (s: SymbolInfo, on: boolean) => void;
  onAuthError: (err: unknown) => void;
  onChanged: () => void;
  prefill: AutoPrefill | null;
  onPrefillUsed: () => void;
}

/** Automatic paper trading: strategies trading this paper account by their own rules. */
export default function AutoPanel({ account, catalogue, favourites, onToggleFavourite, onAuthError, onChanged, prefill, onPrefillUsed }: Props) {
  const [runs, setRuns] = useState<AutoRun[]>([]);
  const [options, setOptions] = useState<AutoOptions | null>(null);
  const [adding, setAdding] = useState(false);
  const [showStopped, setShowStopped] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((background = false) => {
    api.autoRuns(account.id, background).then((r) => setRuns(r.runs)).catch(onAuthError);
  }, [account.id, onAuthError]);

  useEffect(() => {
    load();
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") load(true); }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);
  useEffect(() => { api.autoOptions().then(setOptions).catch(onAuthError); }, [onAuthError]);
  useEffect(() => { if (prefill) setAdding(true); }, [prefill]);

  function change(run: AutoRun, action: "pause" | "resume" | "stop") {
    let closeOpen = false;
    if (action === "stop") {
      if (!window.confirm(`Stop ${run.strategyName} on ${displayCode(run.symbol)}? A stopped run can't be restarted, but its results are kept.`)) return;
    }
    if (action !== "resume" && run.openTradeId) {
      closeOpen = window.confirm("It has an open trade. Close that trade now at the market price too?\n\nOK closes it. Cancel leaves it open with its stop-loss, for you to manage.");
    }
    api.changeAutoRun(run.id, action, closeOpen).then(() => { setError(null); load(); onChanged(); }).catch((err) => {
      onAuthError(err);
      setError(err instanceof Error ? err.message : "That didn't work.");
    });
  }

  const visible = runs.filter((r) => showStopped || r.status !== "stopped");
  const stoppedCount = runs.filter((r) => r.status === "stopped").length;

  return (
    <div className="card auto-panel">
      <h3>Automatic paper trading</h3>
      <p className="muted small-text">
        A strategy trades this account by its own rules: each time a candle finishes, it opens or closes trades exactly as the
        backtest would. Every order goes through the same safeguards as yours (1% risk, the open-risk limit, the daily loss limit
        and the drawdown pause). Pretend money only; nothing is sent to a broker.
      </p>
      {error && <p className="warn stop">{error}</p>}

      {visible.length === 0 && !adding && <p className="muted">No automatic runs on this account yet.</p>}
      {visible.map((run) => <RunCard key={run.id} run={run} onChange={change} />)}
      {stoppedCount > 0 && (
        <button type="button" className="link-button small-text" onClick={() => setShowStopped((v) => !v)}>
          {showStopped ? "Hide" : "Show"} {stoppedCount} stopped run{stoppedCount === 1 ? "" : "s"}
        </button>
      )}

      {adding && options ? (
        <NewRun account={account} options={options} catalogue={catalogue} favourites={favourites}
          onToggleFavourite={onToggleFavourite} onAuthError={onAuthError} prefill={prefill}
          onDone={(started) => { setAdding(false); onPrefillUsed(); if (started) { load(); onChanged(); } }} />
      ) : (
        !account.archived && <button type="button" className="small" onClick={() => setAdding(true)}>+ Start an automatic run</button>
      )}
    </div>
  );
}

function RunCard({ run, onChange }: { run: AutoRun; onChange: (run: AutoRun, action: "pause" | "resume" | "stop") => void }) {
  const bt = run.backtest;
  const lv = run.live;
  const caution = bt.returnPct !== undefined && (bt.returnPct <= 0 || (bt.buyHoldReturnPct !== undefined && bt.returnPct < bt.buyHoldReturnPct));
  return (
    <div className={`auto-run ${run.status}`}>
      <div className="auto-run-head">
        <div>
          <b>{run.strategyName}</b> · {displayCode(run.symbol)} <span className="muted">{run.name !== run.symbol ? run.name : ""}</span> · {run.timeframe}
          {" · "}{run.direction === "both" ? "buys and shorts" : "buys only"}
        </div>
        <span className={`tag ${run.status === "running" ? "go" : run.status === "paused" ? "caution" : ""}`}>
          {run.status === "running" ? "Running" : run.status === "paused" ? "Paused" : "Stopped"}
        </span>
      </div>
      <p className="auto-msg">{run.message}</p>
      <p className="muted small-text">Started {when(run.createdAt)} · last looked {when(run.lastCheckAt)}</p>

      <table className="auto-compare">
        <thead><tr><th></th><th className="num">Trades</th><th className="num">Win rate</th><th className="num">Average R</th><th className="num">Result</th></tr></thead>
        <tbody>
          <tr>
            <th>Backtest</th>
            <td className="num">{bt.trades ?? "–"}{bt.tradesPerYear ? <span className="muted"> ({num(bt.tradesPerYear, 0)}/yr)</span> : null}</td>
            <td className="num">{num(bt.winRate, 0, "%")}</td>
            <td className="num">{num(bt.avgR, 2)}</td>
            <td className={`num ${(bt.returnPct ?? 0) >= 0 ? "up" : "down"}`}>{num(bt.returnPct, 1, "%")}{bt.years ? <span className="muted"> over {num(bt.years, 1)} yrs</span> : null}</td>
          </tr>
          <tr>
            <th>Paper so far</th>
            <td className="num">{lv.trades}{lv.open ? <span className="muted"> (+{lv.open} open)</span> : null}</td>
            <td className="num">{num(lv.winRate, 0, "%")}</td>
            <td className="num">{num(lv.avgR, 2)}</td>
            <td className={`num ${lv.net >= 0 ? "up" : "down"}`}>£{lv.net.toFixed(2)}</td>
          </tr>
        </tbody>
      </table>
      <p className="muted small-text">
        {lv.trades < JUDGE_AFTER
          ? `${lv.trades} of ${JUDGE_AFTER} closed trades: too few to judge yet. Compare average R and win rate with the backtest once there are ${JUDGE_AFTER} or more.`
          : "Enough trades to compare: if average R is well below the backtest's, the backtest was probably too kind."}
        {" "}Before any real money: at least 3 months and 50 trades here, still ahead after costs.
      </p>
      {caution && <p className="warn caution small-text">The backtest of these rules {bt.returnPct! <= 0 ? "lost money" : "didn't beat simply buying and holding"}. Fine for learning, but don't expect it to do better on paper.</p>}

      {run.status !== "stopped" && (
        <div className="planner-actions">
          {run.status === "running"
            ? <button type="button" className="ghost small" onClick={() => onChange(run, "pause")}>Pause</button>
            : <button type="button" className="small" onClick={() => onChange(run, "resume")}>Resume</button>}
          <button type="button" className="ghost small" onClick={() => onChange(run, "stop")}>Stop</button>
        </div>
      )}
    </div>
  );
}

function NewRun({ account, options, catalogue, favourites, onToggleFavourite, onAuthError, prefill, onDone }: {
  account: PaperAccount; options: AutoOptions; catalogue: Catalogue | null; favourites: SymbolInfo[];
  onToggleFavourite: (s: SymbolInfo, on: boolean) => void; onAuthError: (err: unknown) => void;
  prefill: AutoPrefill | null; onDone: (started: boolean) => void;
}) {
  const known = [...(catalogue?.symbols ?? []), ...favourites];
  const [symbol, setSymbol] = useState<SymbolInfo | undefined>(() => known.find((s) => s.code === (prefill?.symbol ?? "EUR_USD")));
  const [code, setCode] = useState(prefill?.symbol ?? "EUR_USD");
  const [strategy, setStrategy] = useState(prefill?.strategy && options.strategies.some((s) => s.key === prefill.strategy) ? prefill.strategy : options.strategies[0]?.key ?? "");
  const [timeframe, setTimeframe] = useState(prefill?.timeframe ?? "1d");
  const [direction, setDirection] = useState<"long" | "both">(prefill?.direction === "both" ? "both" : "long");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A market found by search isn't in the catalogue: look it up, so the right timeframes are offered.
  useEffect(() => {
    if (symbol && symbol.code === code) return;
    const ctl = new AbortController();
    api.searchMarkets(code, "", ctl.signal).then((r) => {
      const hit = r.results.find((s) => s.code === code);
      if (hit) setSymbol(hit);
    }).catch(() => {});
    return () => ctl.abort();
  }, [code, symbol]);

  const allowed = symbol ? options.timeframes[symbol.provider] ?? [] : [];
  const chosen = options.strategies.find((s) => s.key === strategy);
  const canShort = account.mode === "cfd" && !!chosen?.canShort;
  useEffect(() => {
    if (allowed.length && !allowed.includes(timeframe)) setTimeframe(allowed.includes("1d") ? "1d" : allowed[0]);
  }, [allowed, timeframe]);

  return (
    <form className="new-run" onSubmit={(e) => {
      e.preventDefault();
      setBusy(true);
      setError(null);
      api.startAutoRun({ account_id: account.id, symbol: code, timeframe, strategy, direction: canShort ? direction : "long",
        params: prefill?.strategy === strategy && prefill?.params ? prefill.params : undefined })
        .then(() => onDone(true))
        .catch((err) => { onAuthError(err); setError(err instanceof Error ? err.message : "Couldn't start it."); })
        .finally(() => setBusy(false));
    }}>
      <h4>Start an automatic run on {account.name}</h4>
      <MarketPicker value={code} current={symbol} popular={catalogue?.symbols ?? []} counts={catalogue?.marketCounts ?? {}}
        favourites={favourites} onToggleFavourite={onToggleFavourite} onAuthError={onAuthError}
        onChange={(s) => { setSymbol(s); setCode(s.code); }} />
      <div className="form-row">
        <span className="field-label">Timeframe</span>
        <div className="segmented" role="group" aria-label="Timeframe">
          {allowed.map((t) => <button key={t} type="button" className={timeframe === t ? "on" : ""} onClick={() => setTimeframe(t)}>{t}</button>)}
        </div>
        <span className="muted small-text">
          {symbol && !allowed.length
            ? "UK shares can't trade automatically: their free data is daily only, with no live price to place orders at."
            : "Shorter timeframes would use up the free price data allowance."}
        </span>
      </div>
      <label className="form-row">
        <span className="field-label">Strategy</span>
        <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
          {options.strategies.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
        </select>
        {chosen && <span className="muted small-text">{chosen.summary}</span>}
      </label>
      {prefill?.strategy === strategy && prefill?.params && Object.keys(prefill.params).length > 0 && (
        <p className="muted small-text">Using the settings from your backtest: {Object.entries(prefill.params).map(([k, v]) => `${k} ${v}`).join(", ")}.</p>
      )}
      {canShort && (
        <div className="form-row">
          <span className="field-label">Direction</span>
          <div className="segmented wide">
            <button type="button" className={direction === "long" ? "on" : ""} onClick={() => setDirection("long")}>Buys only</button>
            <button type="button" className={direction === "both" ? "on" : ""} onClick={() => setDirection("both")}>Buys and shorts</button>
          </div>
        </div>
      )}
      <p className="muted small-text">
        It starts from the next finished candle; any setup already on the chart is ignored. Backtest the same strategy, market and
        timeframe first, so you know what to expect. The backtest's figures are saved with the run for comparison.
      </p>
      {error && <p className="form-error">{error}</p>}
      <div className="planner-actions">
        <button type="submit" className="primary" disabled={busy || !strategy || !allowed.includes(timeframe)}>{busy ? "Starting…" : "Start"}</button>
        <button type="button" className="ghost" onClick={() => onDone(false)}>Cancel</button>
      </div>
    </form>
  );
}
