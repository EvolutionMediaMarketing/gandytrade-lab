import { useState } from "react";
import EquityChart from "./EquityChart";
import type { WalkForward } from "./types";

const signed = (v: number | null | undefined, digits = 1) => (v === null || v === undefined ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`);
const money = (v: number) => `£${v.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const month = (ts: number) => new Date(ts * 1000).toLocaleDateString("en-GB", { month: "short", year: "numeric" });
const MARK = { pass: "✓", warn: "!", fail: "✗" } as const;

/** Walk-forward check and robustness verdict, run on demand for the backtest on screen (around 60 backtests). */
export default function WalkForwardCard({ run, onAuthError }: {
  run: () => Promise<WalkForward>; onAuthError: (err: unknown) => void;
}) {
  const [result, setResult] = useState<WalkForward | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function start() {
    setRunning(true);
    setError(null);
    run()
      .then(setResult)
      .catch((err) => { onAuthError(err); setError(err instanceof Error ? err.message : "The walk-forward check didn't run."); })
      .finally(() => setRunning(false));
  }

  if (!result || !result.ok) {
    return (
      <div className="card walk-forward">
        <h3>Walk-forward check and verdict</h3>
        <p className="muted small-text">
          This backtest's settings were chosen by looking at the same history they're tested on, which flatters them. The
          walk-forward check tunes the settings on one stretch of history, trades them on the next stretch it has never seen,
          and repeats that six times. It ends with a verdict: Reject, Watchlist, Incubate or Candidate.
        </p>
        {result && !result.ok && <p className="form-error">{result.reason}</p>}
        {error && <p className="form-error">{error}</p>}
        <button type="button" className="primary" disabled={running} onClick={start}>
          {running ? "Checking… (around 60 backtests)" : "Run the walk-forward check"}
        </button>
        {!running && <span className="muted small-text"> Takes a few seconds to a minute.</span>}
      </div>
    );
  }

  return <WalkForwardResult r={result} running={running} onRerun={start} />;
}

/** The finished check: verdict, checks, unseen-years chart and tables. */
export function WalkForwardResult({ r, running, onRerun }: {
  r: Extract<WalkForward, { ok: true }>; running: boolean; onRerun: () => void;
}) {
  const u = r.unseen;
  return (
    <div className="card walk-forward">
      <h3>Walk-forward check and verdict <span className="muted small-text">— does it work on years it wasn't tuned on?</span></h3>
      {r.warnings.length > 0 && <ul className="warnings">{r.warnings.map((w, i) => <li key={i} className={`warn ${w.level}`}>{w.text}</li>)}</ul>}

      <div className={`wf-verdict ${r.verdict.key}`}>
        <span className="wf-verdict-label">{r.verdict.label}</span>
        <div>
          <p>{r.verdict.text}</p>
          <p className="muted small-text">{r.verdict.passed} of {r.verdict.total} checks passed. Evidence about the past, not a forecast or advice to trade.</p>
        </div>
      </div>

      <p className="headline">{r.headline}</p>

      <ul className="wf-checks">
        {r.checks.map((c) => (
          <li key={c.key} className={`is-${c.status}`}>
            <span className="check-mark" aria-label={c.status}>{MARK[c.status]}</span>
            <span><b>{c.label}.</b> <span className="muted">{c.detail}</span></span>
          </li>
        ))}
      </ul>

      <div className="stats">
        <Stat label="Unseen years" value={signed(u.metrics.returnPct)} tone={u.metrics.returnPct}
          sub={`${signed(u.annualPct)} a year · ${money(u.metrics.final)}`} />
        <Stat label="While tuning" value={`${signed(r.tunedAnnualPct)} a year`} sub="the picks, on the stretches they were picked on" />
        <Stat label="Edge kept" value={r.efficiencyPct === null ? "–" : `${r.efficiencyPct}%`} sub="unseen ÷ tuned yearly return" />
        <Stat label="Your settings, same years" value={signed(r.yours.metrics.returnPct)} tone={r.yours.metrics.returnPct}
          sub={`${signed(r.yours.annualPct)} a year (chosen with hindsight)`} />
      </div>

      <div className="card inner">
        <h3>Unseen years only <span className="legend-key strat">Walk-forward</span> <span className="legend-key bh">Your settings</span>
          <span className="muted small-text">{month(u.from)} to {month(u.to)}, balance carried from stretch to stretch</span></h3>
        <EquityChart strategy={u.equity} buyHold={r.yours.equity} start={r.startBalance} label="Walk-forward" compareLabel="Your settings" />
      </div>

      <h4>Each stretch</h4>
      <div className="table-wrap">
        <table className="trades">
          <thead>
            <tr><th>Tuned on</th><th>Best settings</th><th className="num">Made while tuning</th><th>Then traded</th>
              <th className="num">Unseen result</th><th className="num">Trades</th><th className="num">Your settings</th></tr>
          </thead>
          <tbody>
            {r.windows.map((w) => (
              <tr key={w.testFrom}>
                <td>{month(w.trainFrom)} – {month(w.trainTo)}</td>
                <td>{w.picked}</td>
                <td className="num">{signed(w.tunedReturnPct)}</td>
                <td>{month(w.testFrom)} – {month(w.testTo)}</td>
                <td className={`num ${w.testReturnPct >= 0 ? "up" : "down"}`}>{signed(w.testReturnPct)}</td>
                <td className="num">{w.testTrades}</td>
                <td className="num muted">{signed(w.yoursTestReturnPct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h4>Every setting tried, over the whole history</h4>
      <div className="table-wrap">
        <table className="trades">
          <thead>
            <tr><th>Settings</th><th className="num">Return</th><th className="num">Per year</th><th className="num">Profit factor</th>
              <th className="num">Avg R</th><th className="num">Trades</th><th className="num">Worst fall</th></tr>
          </thead>
          <tbody>
            {r.settings.map((s) => (
              <tr key={s.label} className={s.role === "yours" ? "highlight" : ""}>
                <td>{s.label}</td>
                <td className={`num ${s.returnPct >= 0 ? "up" : "down"}`}>{signed(s.returnPct)}</td>
                <td className="num">{signed(s.annualPct)}</td>
                <td className="num">{s.profitFactor ?? "–"}</td>
                <td className="num">{s.avgR ?? "–"}</td>
                <td className="num">{s.trades}</td>
                <td className="num">{s.maxDrawdownPct.toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small-text">Each length is tried at ×0.5, ×0.75, ×1.5 and ×2, plus the standard settings, all fixed before the test.
        Everything here keeps trading past the drawdown limit so the whole history is judged.</p>

      <ul className="warnings">{r.notes.map((n, i) => <li key={i} className="warn info">{n}</li>)}</ul>
      <button type="button" className="ghost small" disabled={running} onClick={onRerun}>{running ? "Checking…" : "Run it again"}</button>
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
