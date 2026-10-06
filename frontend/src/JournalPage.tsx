import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { money } from "./BacktestPage";
import { displayCode } from "./MarketPicker";
import { Journal, MOOD_LABEL } from "./PaperPage";
import type { JournalTrade, PaperTrade } from "./types";

const FILTERS_KEY = "gt.journal.filters.v1";

interface Filters {
  text: string;
  account: string; // "" = all, else account id
  market: string;
  status: "" | "open" | "closed";
  who: "" | "manual" | "auto";
  result: "" | "win" | "loss";
  mood: string;
  written: "" | "lesson" | "nolesson";
  flags: "" | "broken" | "clean";
  from: string; // yyyy-mm-dd, by the day the trade opened
  to: string;
}

const EMPTY: Filters = { text: "", account: "", market: "", status: "", who: "", result: "", mood: "", written: "", flags: "", from: "", to: "" };

function loadFilters(): Filters {
  try {
    return { ...EMPTY, ...JSON.parse(localStorage.getItem(FILTERS_KEY) || "{}") };
  } catch {
    return EMPTY;
  }
}

const day = (iso: string | null) => (iso ? iso.slice(0, 10) : "");
const shortDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "2-digit" }) : "–";

/** Every journal entry from every paper account in one list, with filters. Click one to read or write it. */
export default function JournalPage({ onAuthError, onShowTrade }: {
  onAuthError: (err: unknown) => void;
  onShowTrade: (t: PaperTrade) => void;
}) {
  const [trades, setTrades] = useState<JournalTrade[] | null>(null);
  const [limited, setLimited] = useState(false);
  const [filters, setFilters] = useState<Filters>(loadFilters);
  const [open, setOpen] = useState<JournalTrade | null>(null);

  const load = useCallback(() => {
    api.journal().then((r) => { setTrades(r.trades); setLimited(r.limited); }).catch(onAuthError);
  }, [onAuthError]);
  useEffect(load, [load]);
  useEffect(() => {
    try {
      localStorage.setItem(FILTERS_KEY, JSON.stringify(filters));
    } catch {
      /* ignore */
    }
  }, [filters]);

  const set = <K extends keyof Filters>(key: K, value: Filters[K]) => setFilters((f) => ({ ...f, [key]: value }));

  const accounts = useMemo(() => {
    const seen = new Map<number, string>();
    (trades ?? []).forEach((t) => seen.set(t.accountId, t.accountName + (t.accountArchived ? " (archived)" : "")));
    return [...seen.entries()];
  }, [trades]);
  const markets = useMemo(() => [...new Set((trades ?? []).map((t) => t.symbol))].sort(), [trades]);

  const shown = useMemo(() => {
    const q = filters.text.trim().toLowerCase();
    return (trades ?? []).filter((t) => {
      if (filters.account && String(t.accountId) !== filters.account) return false;
      if (filters.market && t.symbol !== filters.market) return false;
      if (filters.status && t.status !== filters.status) return false;
      if (filters.who && (filters.who === "auto") !== (t.source === "auto")) return false;
      if (filters.result === "win" && !(t.status === "closed" && (t.pnl ?? 0) > 0)) return false;
      if (filters.result === "loss" && !(t.status === "closed" && (t.pnl ?? 0) <= 0)) return false;
      if (filters.mood && t.mood !== filters.mood) return false;
      if (filters.written === "lesson" && !(t.lesson || t.notes)) return false;
      if (filters.written === "nolesson" && (t.lesson || t.status !== "closed")) return false;
      if (filters.flags === "broken" && t.ruleFlags.length === 0) return false;
      if (filters.flags === "clean" && t.ruleFlags.length > 0) return false;
      if (filters.from && day(t.entryTime) < filters.from) return false;
      if (filters.to && day(t.entryTime) > filters.to) return false;
      if (q) {
        const hay = `${t.symbol} ${displayCode(t.symbol)} ${t.name ?? ""} ${t.reason} ${t.notes} ${t.lesson} ${t.exitReason} ${t.accountName} ${t.strategyName} ${t.ruleFlags.join(" ")}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [trades, filters]);

  const closed = shown.filter((t) => t.status === "closed");
  const wins = closed.filter((t) => (t.pnl ?? 0) > 0).length;
  const net = closed.reduce((a, t) => a + (t.pnl ?? 0), 0);
  const rs = closed.map((t) => t.r).filter((r): r is number => r !== null);
  const avgR = rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : null;
  const active = Object.entries(filters).filter(([, v]) => v !== "").length;

  return (
    <div className="page journal-page">
      <header className="journal-head">
        <h2>Journal</h2>
        <p className="muted small-text">Every trade from every paper account, newest first. Click one to read it, or to write what happened and the lesson.</p>
      </header>

      <div className="card journal-filters" role="search">
        <input type="search" placeholder="Search reasons, notes, lessons, markets…" value={filters.text}
          onChange={(e) => set("text", e.target.value)} aria-label="Search the journal" />
        <select value={filters.account} onChange={(e) => set("account", e.target.value)} aria-label="Account">
          <option value="">All accounts</option>
          {accounts.map(([id, name]) => <option key={id} value={String(id)}>{name}</option>)}
        </select>
        <select value={filters.market} onChange={(e) => set("market", e.target.value)} aria-label="Market">
          <option value="">All markets</option>
          {markets.map((m) => <option key={m} value={m}>{displayCode(m)}</option>)}
        </select>
        <select value={filters.status} onChange={(e) => set("status", e.target.value as Filters["status"])} aria-label="Open or closed">
          <option value="">Open and closed</option><option value="open">Open</option><option value="closed">Closed</option>
        </select>
        <select value={filters.who} onChange={(e) => set("who", e.target.value as Filters["who"])} aria-label="Who placed it">
          <option value="">Yours and automatic</option><option value="manual">Yours</option><option value="auto">Automatic</option>
        </select>
        <select value={filters.result} onChange={(e) => set("result", e.target.value as Filters["result"])} aria-label="Result">
          <option value="">Any result</option><option value="win">Winners</option><option value="loss">Losers</option>
        </select>
        <select value={filters.mood} onChange={(e) => set("mood", e.target.value)} aria-label="Mood">
          <option value="">Any mood</option>
          {Object.entries(MOOD_LABEL).filter(([k]) => k).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
        <select value={filters.written} onChange={(e) => set("written", e.target.value as Filters["written"])} aria-label="Journal written">
          <option value="">Any entry</option><option value="lesson">With notes or a lesson</option><option value="nolesson">Closed, no lesson yet</option>
        </select>
        <select value={filters.flags} onChange={(e) => set("flags", e.target.value as Filters["flags"])} aria-label="Rules">
          <option value="">Any rule score</option><option value="broken">Broke a rule</option><option value="clean">No rules broken</option>
        </select>
        <label className="date-filter"><span>From</span><input type="date" value={filters.from} onChange={(e) => set("from", e.target.value)} /></label>
        <label className="date-filter"><span>To</span><input type="date" value={filters.to} onChange={(e) => set("to", e.target.value)} /></label>
        {active > 0 && <button type="button" className="ghost small" onClick={() => setFilters(EMPTY)}>Clear filters ({active})</button>}
      </div>

      {trades === null ? <p className="muted">Loading…</p> : (
        <>
          <p className="journal-summary">
            <b>{shown.length}</b> of {trades.length} trade{trades.length === 1 ? "" : "s"}
            {closed.length > 0 && <>
              {" · "}{closed.length} closed, {Math.round((wins / closed.length) * 100)}% winners
              {" · "}net <b className={net >= 0 ? "up" : "down"}>{money(net)}</b>
              {avgR !== null && <> · average {avgR.toFixed(2)}R</>}
            </>}
            {limited && <span className="muted"> · showing the newest 2,000</span>}
          </p>
          {shown.length === 0 ? (
            <p className="muted">{trades.length === 0 ? "No trades yet. Place one from the chart with Plan a trade." : "No trades match these filters."}</p>
          ) : (
            <div className="table-wrap card">
              <table className="trades journal-table">
                <thead>
                  <tr><th>Opened</th><th>Market</th><th>Side</th><th>Account</th><th className="num">Result</th><th>Mood</th>
                    <th>Why</th><th>Lesson</th><th></th></tr>
                </thead>
                <tbody>
                  {shown.map((t) => (
                    <tr key={t.id} className={`clickable ${open?.id === t.id ? "highlight" : ""}`}
                      onClick={(e) => { if (!(e.target as HTMLElement).closest("button")) setOpen(t); }}>
                      <td>{shortDate(t.entryTime)}</td>
                      <td>{displayCode(t.symbol)}</td>
                      <td>{t.side === "long" ? "Buy" : "Short"}{t.source === "auto" && <span className="tag auto" title={t.strategyName}>Auto</span>}</td>
                      <td className="muted">{t.accountName}</td>
                      <td className={`num ${t.status === "open" ? "muted" : (t.pnl ?? 0) >= 0 ? "up" : "down"}`}>
                        {t.status === "open" ? "Open" : <>{money(t.pnl ?? 0)}{t.r !== null && <span className="muted"> {t.r.toFixed(1)}R</span>}</>}
                      </td>
                      <td>{MOOD_LABEL[t.mood] ?? "–"}</td>
                      <td className="journal-text" title={t.reason}>
                        {t.source === "auto" ? <span className="muted">{t.strategyName || "Automatic"}</span> : t.reason || "–"}
                        {t.ruleFlags.length > 0 && <span className="tag stop" title={t.ruleFlags.join("\n")}>{t.ruleFlags.length} rule{t.ruleFlags.length === 1 ? "" : "s"}</span>}
                      </td>
                      <td className="journal-text" title={t.lesson || t.notes}>
                        {t.lesson || (t.notes ? <span className="muted">{t.notes}</span> : t.status === "closed" ? <span className="muted">Not written</span> : "")}
                      </td>
                      <td className="row-actions">
                        <button type="button" className="ghost small" onClick={() => onShowTrade(t)}>Chart</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {open && <Journal trade={open} onClose={() => setOpen(null)} onSaved={load} onAuthError={onAuthError} />}
    </div>
  );
}
