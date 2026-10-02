import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { money } from "./BacktestPage";
import { displayCode } from "./MarketPicker";
import type { PaperAccount, PaperEvent, PaperTrade } from "./types";
import { useLivePrices } from "./useLivePrices";

const REFRESH_MS = 30_000;
const MOOD_LABEL: Record<string, string> = {
  calm: "Calm", confident: "Confident", unsure: "Unsure", anxious: "Anxious", bored: "Bored", fomo: "Fear of missing out", frustrated: "Frustrated",
};
const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "–";
const fmt = (v: number | null | undefined, p = 5) => (v === null || v === undefined ? "–" : v.toFixed(Math.min(6, Math.max(2, p))));
const pct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;

export default function PaperPage({ onAuthError, onOpenChart }: { onAuthError: (err: unknown) => void; onOpenChart: (symbol: string) => void }) {
  const [accounts, setAccounts] = useState<PaperAccount[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<PaperAccount | null>(null);
  const [journal, setJournal] = useState<PaperTrade | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const loadAccounts = useCallback(() => {
    api.paperAccounts().then((r) => {
      setAccounts(r.accounts);
      setSelected((s) => s ?? r.accounts.find((a) => !a.archived)?.id ?? null);
    }).catch(onAuthError);
  }, [onAuthError]);

  const loadDetail = useCallback((background = false) => {
    if (selected === null) return;
    api.paperAccount(selected, background).then((d) => { setDetail(d); setError(null); }).catch((err) => {
      onAuthError(err);
      setError(err instanceof Error ? err.message : "Couldn't load the account.");
    });
  }, [selected, onAuthError]);

  useEffect(loadAccounts, [loadAccounts]);
  useEffect(() => {
    loadDetail();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") loadDetail(true);
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [loadDetail]);

  // Live prices for open trades on OANDA markets: move "Now" and the profit between the 30-second refreshes.
  const openSymbols = (detail?.open ?? []).map((t) => t.symbol);
  const { prices: live } = useLivePrices(openSymbols, openSymbols.length > 0);
  const withLive = (t: PaperTrade): PaperTrade => {
    const lp = live[t.symbol];
    if (!lp || t.price == null || !t.valueGbp || t.unrealised === undefined) return t;
    const ratePerGbp = (t.units * t.price) / t.valueGbp; // price-currency units per £1
    const unrealised = t.unrealised + ((lp.mid - t.price) * (t.side === "long" ? 1 : -1) * t.units) / ratePerGbp;
    return { ...t, price: lp.mid, unrealised };
  };

  function act(p: Promise<unknown>) {
    p.then(() => { loadDetail(); loadAccounts(); }).catch((err) => {
      onAuthError(err);
      setError(err instanceof Error ? err.message : "That didn't work.");
    });
  }

  return (
    <div className="page paper">
      <aside className="paper-accounts">
        <h2>Paper accounts</h2>
        <p className="muted small-text">Pretend money on live prices. Place trades from the chart with <b>Plan a trade</b>.</p>
        <ul>
          {accounts.filter((a) => !a.archived).map((a) => (
            <li key={a.id}>
              <button type="button" className={selected === a.id ? "acct on" : "acct"} onClick={() => { setSelected(a.id); setJournal(null); }}>
                <span className="acct-name">{a.name}</span>
                <span className="muted">{a.mode === "cash" ? "Real shares" : "CFD / spread bet"} · {a.openCount} open</span>
                <span className="acct-eq">{money(a.equity)}</span>
                <span className={a.returnPct >= 0 ? "up" : "down"}>{pct(a.returnPct)}</span>
                {a.halted && <span className="tag stop">Paused</span>}
              </button>
            </li>
          ))}
        </ul>
        {creating ? <NewAccount onDone={(id) => { setCreating(false); loadAccounts(); if (id) setSelected(id); }} onAuthError={onAuthError} />
          : <button type="button" className="ghost small" onClick={() => setCreating(true)}>+ New paper account</button>}
      </aside>

      <section className="paper-main">
        {error && <p className="warn stop">{error}</p>}
        {detail && (
          <>
            <header className="result-head">
              <h2>{detail.name} <span className="muted">{detail.mode === "cash" ? "Real shares, no leverage" : "CFD / spread bet"}</span></h2>
              <p className="muted small-text">Started with {money(detail.startingBalance, 0)}{detail.deposits ? ` plus ${money(detail.deposits, 0)} added` : ""} · risk {detail.riskPct}% a trade · at most {detail.maxOpenRiskPct}% at risk at once · daily loss limit {detail.dailyLossPct}% · pauses after a {detail.maxDrawdownPct}% fall · <a href="#/settings">change</a></p>
            </header>
            {detail.halted && (
              <div className="warn stop">
                {detail.haltReason}{" "}
                <button type="button" className="link-button" onClick={() => {
                  if (window.confirm("Resume trading on this account? Do it only once you've reviewed what led to the fall.")) {
                    act(api.changePaperAccount(detail.id, { resume: true }));
                  }
                }}>I've reviewed it: resume</button>
              </div>
            )}
            {!detail.halted && detail.block && <p className="warn caution">{detail.block}</p>}

            <div className="stats">
              <Stat label="Account value" value={money(detail.equity)} sub={`Cash ${money(detail.cash)}`} />
              <Stat label="Return" value={pct(detail.returnPct)} tone={detail.returnPct} />
              <Stat label={detail.mode === "cash" ? "Free to invest" : "Free margin"} value={money(detail.buyingPower)} />
              <Stat label="At risk now" value={money(detail.openRisk)} sub={`Limit ${money(detail.openRiskLimit)} (${detail.maxOpenRiskPct}%)`} />
            </div>

            <div className="card">
              <h3>Open trades <span className="muted small">(prices update every 30 seconds; the worker closes trades at their stop-loss or target)</span></h3>
              {!detail.open?.length ? <p className="muted">No open trades. Use <b>Plan a trade</b> on the Charts page.</p> : (
                <div className="table-wrap">
                  <table className="trades">
                    <thead><tr><th>Market</th><th>Side</th><th>Opened</th><th>Entry</th><th>Now</th><th>Stop-loss</th><th>Target</th><th className="num">Profit</th><th></th></tr></thead>
                    <tbody>
                      {detail.open.map(withLive).map((t) => (
                        <tr key={t.id}>
                          <td><button type="button" className="link-button" onClick={() => onOpenChart(t.symbol)}>{displayCode(t.symbol)}</button></td>
                          <td>{t.side === "long" ? "Buy" : "Short"}</td>
                          <td>{when(t.entryTime)}</td>
                          <td className="mono">{fmt(t.entryPrice, t.precision)}</td>
                          <td className="mono">{fmt(t.price, t.precision)}{live[t.symbol] && <i className="live-dot" title="Live price" />}</td>
                          <td className="mono">
                            <EditPrice value={t.stop} precision={t.precision ?? 5} label="stop-loss" onSave={(v) => {
                              const wider = t.side === "long" ? v < t.stop : v > t.stop;
                              if (wider && !window.confirm("That moves the stop-loss further away, which raises your risk. It will be marked in your rule score. Go ahead?")) return;
                              act(api.changePaperTrade(t.id, { stop: v }));
                            }} />
                          </td>
                          <td className="mono">
                            <EditPrice value={t.target} precision={t.precision ?? 5} label="target" onSave={(v) => act(api.changePaperTrade(t.id, { target: v }))} />
                          </td>
                          <td className={`num ${(t.unrealised ?? 0) >= 0 ? "up" : "down"}`}>{money(t.unrealised ?? 0)}</td>
                          <td className="row-actions">
                            <button type="button" className="ghost small" onClick={() => setJournal(t)}>Journal</button>
                            <button type="button" className="ghost small" onClick={() => {
                              if (window.confirm(`Close this ${displayCode(t.symbol)} trade now at the market price?`)) act(api.closePaperTrade(t.id));
                            }}>Close now</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="card">
              <h3>Closed trades</h3>
              {!detail.closed?.length ? <p className="muted">None yet.</p> : (
                <div className="table-wrap">
                  <table className="trades">
                    <thead><tr><th>Closed</th><th>Market</th><th>Side</th><th>Why it closed</th><th className="num">Profit</th><th className="num">R</th><th className="num">Rule score</th><th></th></tr></thead>
                    <tbody>
                      {detail.closed.map((t) => (
                        <tr key={t.id} className="clickable" onClick={() => setJournal(t)}>
                          <td>{when(t.exitTime)}</td>
                          <td>{displayCode(t.symbol)}</td>
                          <td>{t.side === "long" ? "Buy" : "Short"}</td>
                          <td>{t.exitReason}</td>
                          <td className={`num ${(t.pnl ?? 0) >= 0 ? "up" : "down"}`}>{money(t.pnl)}</td>
                          <td className="num">{t.r === null ? "–" : t.r.toFixed(2)}</td>
                          <td className={`num score s${Math.round(t.ruleScore / 25)}`}>{t.ruleScore}</td>
                          <td>{t.lesson ? "" : <span className="muted small">add a lesson</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="muted small-text">Rule score: 100 means you followed your plan, whatever the profit. Each rule broken takes off 25.</p>
            </div>
          </>
        )}
      </section>

      {journal && <Journal trade={journal} onClose={() => setJournal(null)} onSaved={() => { loadDetail(); }} onAuthError={onAuthError} />}
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

function EditPrice({ value, precision, label, onSave }: { value: number | null; precision: number; label: string; onSave: (v: number) => void }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  if (!editing) {
    return (
      <button type="button" className="link-button mono" title={`Change the ${label}`}
        onClick={() => { setText(value === null ? "" : value.toFixed(precision)); setEditing(true); }}>
        {value === null ? "add" : value.toFixed(precision)}
      </button>
    );
  }
  return (
    <span className="edit-price">
      <input type="number" step="any" autoFocus value={text} onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && Number(text) > 0) { onSave(Number(text)); setEditing(false); }
          if (e.key === "Escape") setEditing(false);
        }} />
      <button type="button" className="ghost small" onClick={() => { if (Number(text) > 0) onSave(Number(text)); setEditing(false); }}>Save</button>
    </span>
  );
}

function NewAccount({ onDone, onAuthError }: { onDone: (id?: number) => void; onAuthError: (err: unknown) => void }) {
  const [name, setName] = useState("");
  const [balance, setBalance] = useState("200");
  const [mode, setMode] = useState<"cash" | "cfd">("cfd");
  const [error, setError] = useState<string | null>(null);
  return (
    <form className="new-account" onSubmit={(e) => {
      e.preventDefault();
      api.newPaperAccount({ name: name || "Paper account", starting_balance: Number(balance) || 200, mode, risk_pct: 1 })
        .then((a) => onDone(a.id))
        .catch((err) => { onAuthError(err); setError(err instanceof Error ? err.message : "Couldn't create it."); });
    }}>
      <label><span>Name</span><input value={name} maxLength={60} onChange={(e) => setName(e.target.value)} placeholder="e.g. Ichimoku practice" /></label>
      <label><span>Starting balance (£)</span><input type="number" min={10} step="any" value={balance} onChange={(e) => setBalance(e.target.value)} /></label>
      <div className="segmented wide">
        <button type="button" className={mode === "cash" ? "on" : ""} onClick={() => setMode("cash")}>Real shares</button>
        <button type="button" className={mode === "cfd" ? "on" : ""} onClick={() => setMode("cfd")}>CFD / spread bet</button>
      </div>
      {error && <p className="form-error">{error}</p>}
      <div className="planner-actions">
        <button type="submit" className="primary">Create</button>
        <button type="button" className="ghost" onClick={() => onDone()}>Cancel</button>
      </div>
    </form>
  );
}

function Journal({ trade, onClose, onSaved, onAuthError }: { trade: PaperTrade; onClose: () => void; onSaved: () => void; onAuthError: (err: unknown) => void }) {
  const [notes, setNotes] = useState(trade.notes);
  const [lesson, setLesson] = useState(trade.lesson);
  const [events, setEvents] = useState<PaperEvent[]>([]);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setNotes(trade.notes);
    setLesson(trade.lesson);
    setSaved(false);
    api.paperEvents(trade.id).then((r) => setEvents(r.events)).catch(onAuthError);
  }, [trade, onAuthError]);

  return (
    <div className="drawer" role="dialog" aria-label="Trade journal">
      <div className="drawer-head">
        <h2>{trade.side === "long" ? "Buy" : "Short"} {displayCode(trade.symbol)}</h2>
        <button type="button" className="ghost" onClick={onClose} aria-label="Close the journal">×</button>
      </div>
      <dl className="facts">
        <dt>Status</dt><dd className="text">{trade.status === "open" ? "Open" : trade.exitReason}</dd>
        <dt>Entry</dt><dd>{fmt(trade.entryPrice, trade.precision)}</dd>
        {trade.exitPrice !== null && <><dt>Exit</dt><dd>{fmt(trade.exitPrice, trade.precision)}</dd></>}
        <dt>Stop-loss</dt><dd>{fmt(trade.stop, trade.precision)}{trade.stop !== trade.initialStop ? ` (was ${fmt(trade.initialStop, trade.precision)})` : ""}</dd>
        <dt>Risked</dt><dd>{money(trade.riskGbp)}</dd>
        {trade.pnl !== null && <><dt>Result</dt><dd className={trade.pnl >= 0 ? "up" : "down"}>{money(trade.pnl)}{trade.r !== null ? ` (${trade.r.toFixed(2)}R)` : ""}</dd></>}
        <dt>Rule score</dt><dd>{trade.ruleScore}</dd>
      </dl>
      {trade.ruleFlags.length > 0 && <ul className="warnings">{trade.ruleFlags.map((f) => <li key={f} className="warn caution">{f}</li>)}</ul>}
      <p><b>Trend you saw:</b> {trade.trend || "–"} · <b>Mood:</b> {MOOD_LABEL[trade.mood] ?? "–"}</p>
      <p><b>Why you took it:</b> {trade.reason || "–"}</p>
      <label className="form-row"><span className="field-label">Notes</span>
        <textarea rows={4} maxLength={2000} value={notes} onChange={(e) => { setNotes(e.target.value); setSaved(false); }}
          placeholder="What happened? Did you stick to the plan?" /></label>
      <label className="form-row"><span className="field-label">Lesson (one line)</span>
        <input maxLength={500} value={lesson} onChange={(e) => { setLesson(e.target.value); setSaved(false); }}
          placeholder="e.g. Waited for the candle to close before entering. Worth repeating." /></label>
      <div className="planner-actions">
        <button type="button" className="primary" onClick={() => {
          api.changePaperTrade(trade.id, { notes, lesson }).then(() => { setSaved(true); onSaved(); }).catch(onAuthError);
        }}>Save journal</button>
        {saved && <span className="muted">Saved.</span>}
      </div>
      <h3>Fill record</h3>
      <ul className="events">
        {events.map((e, i) => (
          <li key={i}>
            <span className="muted">{when(e.at)}</span> {e.kind.replace("_", " ")}
            {e.price !== null && <> at <b className="mono">{fmt(e.price, trade.precision)}</b></>}
            {e.mid !== null && <span className="muted"> (market price {fmt(e.mid, trade.precision)}{e.quoteTs ? `, quoted ${new Date(e.quoteTs * 1000).toLocaleTimeString("en-GB")}` : ""})</span>}
            {e.detail && <span className="muted"> · {e.detail}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
