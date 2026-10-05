import { useEffect, useState } from "react";
import { api } from "./api";
import { money } from "./BacktestPage";
import EquityChart from "./EquityChart";
import { displayCode } from "./MarketPicker";
import type { PaperAccount, Performance, PerfStats } from "./types";

const pct = (v: number | null | undefined, sign = true) =>
  v === null || v === undefined ? "–" : `${sign && v > 0 ? "+" : ""}${v.toFixed(1)}%`;
const num = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "–" : v.toFixed(d));
const LEVEL_CLASS = { stop: "warn stop", caution: "warn caution", info: "warn info", good: "warn good" } as const;

/** How each paper account is doing, and what the app notices about your habits. */
export default function DashboardPage({ onAuthError }: { onAuthError: (err: unknown) => void }) {
  const [accounts, setAccounts] = useState<PaperAccount[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [perf, setPerf] = useState<Performance | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [exportText, setExportText] = useState<string | null>(null);

  useEffect(() => {
    api.paperAccounts().then((r) => {
      const live = r.accounts.filter((a) => !a.archived);
      setAccounts(live);
      setSelected((s) => s ?? live[0]?.id ?? null);
    }).catch(onAuthError);
  }, [onAuthError]);

  useEffect(() => {
    if (selected === null) return;
    setPerf(null);
    setCopied(null);
    setExportText(null);
    api.performance(selected).then(setPerf).catch(onAuthError);
  }, [selected, onAuthError]);

  function copyForCoach() {
    if (selected === null) return;
    api.coachExport(selected).then(async ({ text }) => {
      try {
        await navigator.clipboard.writeText(text);
        setCopied("Copied. Paste it into a chat with Claude for a coaching review.");
        setExportText(null);
      } catch {
        setExportText(text);  // the browser blocked copying: show it to copy by hand
        setCopied("Select the text below and copy it.");
      }
    }).catch(onAuthError);
  }

  const p = perf;
  return (
    <div className="page dashboard">
      <header className="research-head">
        <h2>Dashboard</h2>
        <p className="muted">How each paper account is doing, worked out from its closed trades, and what the app notices about your habits.</p>
        <div className="chips">
          {accounts.map((a) => (
            <button key={a.id} type="button" className={a.id === selected ? "chip on" : "chip"} onClick={() => setSelected(a.id)}>{a.name}</button>
          ))}
        </div>
      </header>

      {!p ? <div className="empty-state"><p className="muted">Loading…</p></div> : (
        <>
          <div className="stats">
            <Stat label="Account value" value={money(p.account.equity)} sub={`${pct(p.account.returnPct)} on ${money(p.account.funded, 0)} · ${p.account.openCount} open`} tone={p.account.returnPct} />
            <Stat label="Closed trades" value={String(p.all.trades)} sub={`${p.manual.trades} yours · ${p.auto.trades} automatic`} />
            <Stat label="Win rate" value={pct(p.all.winRate, false)} sub={`${p.all.wins} won · ${p.all.losses} lost`} />
            <Stat label="Average win / loss" value={`${money(p.all.avgWin)} / ${money(p.all.avgLoss)}`} sub={p.all.payoff ? `Wins are ${p.all.payoff}× the losses` : undefined} />
            <Stat label="Expectancy" value={money(p.all.expectancy)} sub="What an average trade made, after costs" tone={p.all.expectancy ?? 0} />
            <Stat label="Average R" value={num(p.all.avgR)} sub="Profit per trade in units of the risk taken" tone={p.all.avgR ?? 0} />
            <Stat label="Worst fall" value={pct(-p.maxDrawdownPct, false)} sub={`Now ${p.currentDrawdownPct}% below the high · pauses at ${p.account.maxDrawdownLimit}%`} />
            <Stat label="Rule score (your trades)" value={p.ruleScore === null ? "–" : String(p.ruleScore)} sub="90+ before any real money" />
          </div>

          <div className="card">
            <h3>What the app noticed</h3>
            <ul className="warnings">
              {p.feedback.map((f) => <li key={f.title} className={LEVEL_CLASS[f.level]}><b>{f.title}.</b> {f.text}</li>)}
            </ul>
          </div>

          <div className="card">
            <h3>Balance over time</h3>
            <p className="muted small-text">After each closed trade, then today's value including open trades.</p>
            <EquityChart strategy={p.curve} start={p.account.funded} label="Account" />
          </div>

          <div className="card">
            <h3>Yours and automatic, side by side</h3>
            <div className="table-wrap">
              <table className="trades">
                <thead><tr><th></th><th className="num">Trades</th><th className="num">Win rate</th><th className="num">Avg win</th><th className="num">Avg loss</th><th className="num">Expectancy</th><th className="num">Avg R</th><th className="num">Costs</th><th className="num">Net</th></tr></thead>
                <tbody>
                  {([["All trades", p.all], ["Your own", p.manual], ["Automatic", p.auto]] as [string, PerfStats][]).map(([name, s]) => (
                    <tr key={name}>
                      <th>{name}</th><td className="num">{s.trades}</td><td className="num">{pct(s.winRate, false)}</td>
                      <td className="num">{money(s.avgWin)}</td><td className="num">{money(s.avgLoss)}</td>
                      <td className={`num ${(s.expectancy ?? 0) >= 0 ? "up" : "down"}`}>{money(s.expectancy)}</td>
                      <td className="num">{num(s.avgR)}</td><td className="num">{money(s.costs)}</td>
                      <td className={`num ${s.net >= 0 ? "up" : "down"}`}>{money(s.net)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {p.breakdown.length > 0 && (
            <div className="card">
              <h3>By strategy and market</h3>
              <div className="table-wrap">
                <table className="trades">
                  <thead><tr><th>Who</th><th>Market</th><th className="num">Trades</th><th className="num">Win rate</th><th className="num">Avg R</th><th className="num">Costs</th><th className="num">Net</th></tr></thead>
                  <tbody>
                    {p.breakdown.map((b) => (
                      <tr key={`${b.label}-${b.symbol}`}>
                        <td>{b.label}</td><td>{displayCode(b.symbol)}</td><td className="num">{b.trades}</td>
                        <td className="num">{pct(b.winRate, false)}</td><td className="num">{num(b.avgR)}</td>
                        <td className="num">{money(b.costs)}</td><td className={`num ${b.net >= 0 ? "up" : "down"}`}>{money(b.net)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="card">
            <h3>Coaching</h3>
            <p className="muted small-text">
              Copies a summary of this account (figures, what the app noticed, automatic runs and your last 20 trades with their
              lessons) to paste into a chat with Claude for a coaching review. It contains no keys or personal details.
            </p>
            <div className="planner-actions">
              <button type="button" className="primary" onClick={copyForCoach}>Copy for a coaching chat</button>
              {copied && <span className="muted">{copied}</span>}
            </div>
            {exportText && <textarea className="export-text" readOnly rows={14} value={exportText} onFocus={(e) => e.currentTarget.select()} />}
          </div>
        </>
      )}
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
