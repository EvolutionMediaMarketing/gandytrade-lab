import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import MarketPicker, { displayCode } from "./MarketPicker";
import type { AutoOptions, AutoPrefill, AutoRun, Catalogue, PaperAccount, PaperTrade, SymbolInfo } from "./types";

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
  accounts: PaperAccount[];
  onSwitchAccount: (id: number) => void;
  /** This account's trades (open and closed), to list under each run. */
  trades: PaperTrade[];
  onShowTrade: (t: PaperTrade, opts?: { others?: PaperTrade[]; all?: boolean; label?: string }) => void;
}

/** Automatic paper trading: strategies trading this paper account by their own rules. */
export default function AutoPanel({ account, catalogue, favourites, onToggleFavourite, onAuthError, onChanged, prefill, onPrefillUsed, accounts, onSwitchAccount,
  trades, onShowTrade }: Props) {
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
      {visible.map((run) => (
        <RunCard key={run.id} run={run} onChange={change} trades={trades.filter((t) => t.autoRunId === run.id)} onShowTrade={onShowTrade} />
      ))}
      {stoppedCount > 0 && (
        <button type="button" className="link-button small-text" onClick={() => setShowStopped((v) => !v)}>
          {showStopped ? "Hide" : "Show"} {stoppedCount} stopped run{stoppedCount === 1 ? "" : "s"}
        </button>
      )}

      {adding && options ? (
        <NewRun account={account} accounts={accounts} options={options} catalogue={catalogue} favourites={favourites}
          onToggleFavourite={onToggleFavourite} onAuthError={onAuthError} prefill={prefill}
          onDone={(startedOn) => {
            setAdding(false);
            onPrefillUsed();
            if (startedOn === null) return;
            if (startedOn !== account.id) onSwitchAccount(startedOn);  // show the account it went on
            else { load(); onChanged(); }
          }} />
      ) : (
        !account.archived && <button type="button" className="small" onClick={() => setAdding(true)}>+ Start an automatic run</button>
      )}
    </div>
  );
}

const SHOW_TRADES = 8;

function RunCard({ run, onChange, trades, onShowTrade }: {
  run: AutoRun; onChange: (run: AutoRun, action: "pause" | "resume" | "stop") => void;
  trades: PaperTrade[]; onShowTrade: (t: PaperTrade, opts?: { others?: PaperTrade[]; all?: boolean; label?: string }) => void;
}) {
  const [allTrades, setAllTrades] = useState(false);
  // Open first, then the most recently closed.
  const ordered = [...trades].sort((a, b) =>
    (a.status === "open" ? 0 : 1) - (b.status === "open" ? 0 : 1) ||
    Date.parse(b.exitTime ?? b.entryTime) - Date.parse(a.exitTime ?? a.entryTime));
  const shown = allTrades ? ordered : ordered.slice(0, SHOW_TRADES);
  const byTime = [...trades].sort((a, b) => Date.parse(a.entryTime) - Date.parse(b.entryTime));
  const label = `${run.strategyName}${Object.keys(run.params ?? {}).length ? ` (${Object.values(run.params).join("/")})` : ""}`;
  const showOne = (t: PaperTrade) => onShowTrade(t, { others: byTime, label });
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
      {trades.length > 0 && (
        <div className="table-wrap">
          <table className="trades auto-trades">
            <caption className="muted small-text">
              This run's trades: click one to see it on the chart, or{" "}
              <button type="button" className="link-button" onClick={() => onShowTrade(byTime[byTime.length - 1], { others: byTime, all: true, label })}>
                show all {trades.length} on one chart
              </button>
            </caption>
            <thead><tr><th>Opened</th><th>Side</th><th>Entry</th><th>Status</th><th className="num">Profit</th><th className="num">R</th></tr></thead>
            <tbody>
              {shown.map((t) => {
                const profit = t.status === "open" ? t.unrealised ?? null : t.pnl;
                return (
                  <tr key={t.id} className="clickable" title="Show this trade on the chart" onClick={() => showOne(t)}>
                    <td><button type="button" className="link-button" onClick={(e) => { e.stopPropagation(); showOne(t); }}>{when(t.entryTime)}</button></td>
                    <td>{t.side === "long" ? "Buy" : "Short"}</td>
                    <td className="mono">{t.entryPrice.toFixed(Math.min(6, Math.max(2, t.precision ?? 5)))}</td>
                    <td>{t.status === "open" ? <span className="tag go">Open</span> : <span className="muted">{t.exitReason || "Closed"} · {when(t.exitTime)}</span>}</td>
                    <td className={`num ${(profit ?? 0) >= 0 ? "up" : "down"}`}>{profit === null || profit === undefined ? "–" : `£${profit.toFixed(2)}`}</td>
                    <td className="num">{t.r === null || t.status === "open" ? "–" : t.r.toFixed(2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {ordered.length > SHOW_TRADES && (
            <button type="button" className="link-button small-text" onClick={() => setAllTrades((v) => !v)}>
              {allTrades ? "Show fewer" : `Show all ${ordered.length} trades`}
            </button>
          )}
        </div>
      )}
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

function NewRun({ account, accounts, options, catalogue, favourites, onToggleFavourite, onAuthError, prefill, onDone }: {
  account: PaperAccount; accounts: PaperAccount[]; options: AutoOptions; catalogue: Catalogue | null; favourites: SymbolInfo[];
  onToggleFavourite: (s: SymbolInfo, on: boolean) => void; onAuthError: (err: unknown) => void;
  prefill: AutoPrefill | null; onDone: (startedOn: number | null) => void;
}) {
  // Which paper account: chosen on purpose when arriving from Research or Backtest.
  const [target, setTarget] = useState<string>(prefill ? "" : String(account.id));
  const [newName, setNewName] = useState("");
  const formRef = useRef<HTMLFormElement>(null);
  useEffect(() => { if (prefill) formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }, [prefill]);
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

  const chosen = options.strategies.find((s) => s.key === strategy);
  const SHORT = ["1m", "5m", "15m"];
  const allowed = (symbol ? options.timeframes[symbol.provider] ?? [] : [])
    .filter((t) => !chosen?.intradayOnly || SHORT.includes(t));  // scalpers only run on short candles
  const targetAccount = accounts.find((a) => String(a.id) === target);
  const targetMode = target === "new" ? "cfd" : targetAccount?.mode;
  const canShort = targetMode === "cfd" && !!chosen?.canShort;
  const suggestedName = `${chosen?.name.replace(" (scalp)", "") ?? "Auto"} – ${displayCode(code)}`.slice(0, 60);
  useEffect(() => {
    if (allowed.length && !allowed.includes(timeframe)) {
      const preferred = chosen?.intradayOnly ? chosen.suggestedTimeframe || "5m" : "1d";
      setTimeframe(allowed.includes(preferred) ? preferred : allowed[0]);
    }
  }, [allowed, timeframe, chosen]);

  return (
    <form ref={formRef} className="new-run" onSubmit={async (e) => {
      e.preventDefault();
      setBusy(true);
      setError(null);
      try {
        let accountId = Number(target);
        let made: PaperAccount | null = null;
        if (target === "new") {
          made = await api.newPaperAccount({ name: (newName.trim() || suggestedName), starting_balance: 200, mode: "cfd", risk_pct: 1 });
          accountId = made.id;
        }
        try {
          await api.startAutoRun({ account_id: accountId, symbol: code, timeframe, strategy, direction: canShort ? direction : "long",
            params: prefill?.strategy === strategy && prefill?.params ? prefill.params : undefined });
        } catch (err) {
          // Don't leave an empty account behind if the run couldn't start.
          if (made) await api.deletePaperAccount(made.id, made.name).catch(() => undefined);
          throw err;
        }
        onDone(accountId);
      } catch (err) {
        onAuthError(err);
        setError(err instanceof Error ? err.message : "Couldn't start it.");
      } finally {
        setBusy(false);
      }
    }}>
      <h4>Start an automatic run</h4>
      <label className="form-row">
        <span className="field-label">Paper account</span>
        <select value={target} onChange={(e) => setTarget(e.target.value)} required>
          <option value="" disabled>Choose a paper account…</option>
          {accounts.filter((a) => !a.archived).map((a) => (
            <option key={a.id} value={String(a.id)}>
              {a.name} ({a.mode === "cash" ? "real shares" : "CFD / spread bet"}, {a.openCount} open
              {a.autoRunning ? `, ${a.autoRunning} automatic run${a.autoRunning === 1 ? "" : "s"}` : ""})
            </option>
          ))}
          <option value="new">A new CFD account (£200) just for this…</option>
        </select>
        <span className="muted small-text">
          Give each strategy its own account, so its results aren't mixed with other trades.
          {targetAccount?.autoRunning ? " This account already has automatic runs." : ""}
        </span>
      </label>
      {target === "new" && (
        <label className="form-row">
          <span className="field-label">New account name</span>
          <input value={newName} maxLength={60} placeholder={suggestedName} onChange={(e) => setNewName(e.target.value)} />
        </label>
      )}
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
        <button type="submit" className="primary" disabled={busy || !target || !strategy || !allowed.includes(timeframe)}>{busy ? "Starting…" : "Start"}</button>
        <button type="button" className="ghost" onClick={() => onDone(null)}>Cancel</button>
      </div>
    </form>
  );
}
