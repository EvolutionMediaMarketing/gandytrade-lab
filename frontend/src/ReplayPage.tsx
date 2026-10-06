import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { money } from "./BacktestPage";
import ChartView, { type ChartMarker, type ShownTrade } from "./ChartView";
import MarketPicker, { displayCode } from "./MarketPicker";
import {
  atr, begin, ended, equityNow, moveStop, openPnl, placeOrder, score, step,
  type ReplayMarket, type ReplayState, type Score,
} from "./replayEngine";
import type { ActiveIndicator, Catalogue, ChartData, ReplayData, ReplaySessionRow, SymbolInfo } from "./types";
import type { Time } from "lightweight-charts";

const TIMEFRAMES = [["1h", "1 hour"], ["4h", "4 hours"], ["1d", "Daily"], ["1w", "Weekly"]] as const;
const LENGTHS = [100, 250, 500];
const SPEEDS = [1, 2, 5];

interface Props {
  catalogue: Catalogue | null;
  favourites: SymbolInfo[];
  onToggleFavourite: (s: SymbolInfo, on: boolean) => void;
  symbol: string; // the Charts page's market, as a starting point
  indicators: ActiveIndicator[];
  style: string;
  onAuthError: (err: unknown) => void;
}

/** Market replay: pick a market and a past date, then step through candle by candle with the future hidden. */
export default function ReplayPage({ catalogue, favourites, onToggleFavourite, symbol, indicators, style, onAuthError }: Props) {
  const [code, setCode] = useState(symbol);
  const [timeframe, setTimeframe] = useState<string>("1d");
  const [when, setWhen] = useState<"random" | "date">("random");
  const [date, setDate] = useState("2015-01-01");
  const [length, setLength] = useState(250);
  const [balance, setBalance] = useState(200);
  const [risk, setRisk] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<ReplayData | null>(null);
  const [history, setHistory] = useState<ReplaySessionRow[]>([]);
  const known = [...(catalogue?.symbols ?? []), ...favourites];

  const loadHistory = useCallback(() => {
    api.replayResults().then((r) => setHistory(r.sessions)).catch(onAuthError);
  }, [onAuthError]);
  useEffect(loadHistory, [loadHistory]);

  function start() {
    setLoading(true);
    setError(null);
    api.replayStart({ symbol: code, timeframe, start: when === "random" ? "random" : date, candles: length, style, indicators })
      .then((d) => setData(d))
      .catch((err) => { onAuthError(err); setError(err instanceof Error ? err.message : "Couldn't start the replay."); })
      .finally(() => setLoading(false));
  }

  if (data) {
    return <Session data={data} balance={balance} risk={risk} onAuthError={onAuthError}
      onQuit={() => { setData(null); loadHistory(); }} onAgain={() => { setData(null); start(); }} />;
  }

  return (
    <div className="page replay-setup">
      <div className="card">
        <h2>Market replay</h2>
        <p className="muted small-text">
          Practise on real history with the future hidden. Pick a market and a date, then step forward one candle at a time,
          placing paper trades as if it were live. Trades fill at the next candle's open with the usual costs and your
          risk per trade. At the end you'll see how you did, against simply holding the market. Months of practice in an evening.
        </p>
        <div className="replay-form">
          <div className="form-row">
            <span className="field-label">Market</span>
            <MarketPicker value={code} current={known.find((s) => s.code === code)} popular={catalogue?.symbols ?? []}
              counts={catalogue?.marketCounts ?? {}} favourites={favourites} onToggleFavourite={onToggleFavourite}
              onAuthError={onAuthError} onChange={(s) => setCode(s.code)} />
          </div>
          <div className="form-row">
            <span className="field-label">Candles</span>
            <div className="segmented" role="group" aria-label="Timeframe">
              {TIMEFRAMES.map(([k, label]) => <button key={k} type="button" className={timeframe === k ? "on" : ""} onClick={() => setTimeframe(k)}>{label}</button>)}
            </div>
          </div>
          <div className="form-row">
            <span className="field-label">Start</span>
            <div className="segmented" role="group" aria-label="Start">
              <button type="button" className={when === "random" ? "on" : ""} onClick={() => setWhen("random")}>A random date</button>
              <button type="button" className={when === "date" ? "on" : ""} onClick={() => setWhen("date")}>A date I choose</button>
            </div>
            {when === "date" && <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />}
            <span className="muted small-text">{when === "random" ? "Best for honest practice: you won't remember what happened next." : "Good for studying a period, but you may remember how it went."}</span>
          </div>
          <div className="form-row">
            <span className="field-label">How many candles to play</span>
            <div className="segmented" role="group" aria-label="Length">
              {LENGTHS.map((n) => <button key={n} type="button" className={length === n ? "on" : ""} onClick={() => setLength(n)}>{n}</button>)}
            </div>
          </div>
          <div className="param-grid">
            <label><span>Starting balance (£)</span><input type="number" min={10} step="any" value={balance} onChange={(e) => setBalance(Math.max(10, Number(e.target.value) || 200))} /></label>
            <label><span>Risk per trade (%)</span><input type="number" min={0.1} max={2} step={0.1} value={risk} onChange={(e) => setRisk(Math.min(2, Math.max(0.1, Number(e.target.value) || 1)))} /></label>
          </div>
          <p className="muted small-text">The chart uses the indicators and style you've set on the Charts page{indicators.length ? ` (${indicators.length} indicator${indicators.length === 1 ? "" : "s"})` : ""}.</p>
          {error && <p className="form-error">{error}</p>}
          <button type="button" className="primary" disabled={loading} onClick={start}>{loading ? "Loading history…" : "Start the replay"}</button>
        </div>
      </div>

      {history.length > 0 && (
        <div className="card">
          <h3>Your replays</h3>
          <div className="table-wrap">
            <table className="trades">
              <thead><tr><th>Played</th><th>Market</th><th>Period</th><th className="num">Trades</th><th className="num">You</th>
                <th className="num">Holding</th><th className="num">Worst fall</th><th className="num">Avg R</th><th>Lesson</th></tr></thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id}>
                    <td>{new Date(h.createdAt).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}</td>
                    <td>{displayCode(h.symbol)} <span className="muted">{h.timeframe}</span></td>
                    <td className="muted">{monthYear(h.startTs)} – {monthYear(h.endTs)}</td>
                    <td className="num">{h.trades}{h.trades ? <span className="muted"> ({Math.round((h.wins / h.trades) * 100)}% won)</span> : null}</td>
                    <td className={`num ${h.returnPct >= 0 ? "up" : "down"}`}>{pct(h.returnPct)}</td>
                    <td className="num muted">{pct(h.buyHoldPct)}</td>
                    <td className="num">{h.maxDrawdownPct.toFixed(1)}%</td>
                    <td className="num">{h.avgR === null ? "–" : h.avgR.toFixed(2)}</td>
                    <td className="journal-text" title={h.lesson}>{h.lesson || <span className="muted">–</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

const pct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
const monthYear = (ts: number) => new Date(ts * 1000).toLocaleDateString("en-GB", { month: "short", year: "numeric" });
const dateOf = (ts: number, tf: string) => new Date(ts * 1000).toLocaleString("en-GB",
  tf.endsWith("h") || tf.endsWith("m") ? { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" } : { weekday: "short", day: "numeric", month: "short", year: "numeric" });

function Session({ data, balance, risk, onAuthError, onQuit, onAgain }: {
  data: ReplayData; balance: number; risk: number; onAuthError: (err: unknown) => void; onQuit: () => void; onAgain: () => void;
}) {
  const m: ReplayMarket = useMemo(() => ({ bars: data.bars, rates: data.rates, startIndex: data.startIndex, mode: data.mode,
    costs: data.costs, leverage: data.leverage }), [data]);
  const [s, setS] = useState<ReplayState>(() => begin(m, balance, risk));
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(2);
  const [finished, setFinished] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const p = data.symbol.precision;
  const last = data.bars[s.i];
  const isEnd = ended(m, s);

  // Order box: buy or sell, a stop 2 × the typical candle range away, and a 2R target (all editable).
  const [side, setSide] = useState<1 | -1>(1);
  const range = atr(data.bars, s.i);
  const [stopText, setStopText] = useState("");
  const [targetText, setTargetText] = useState("");
  const [useTarget, setUseTarget] = useState(true);
  const suggest = useCallback((sd: 1 | -1) => {
    const price = data.bars[s.i].close;
    const d = 2 * atr(data.bars, s.i);
    setStopText((price - sd * d).toFixed(p));
    setTargetText((price + sd * 2 * d).toFixed(p));
  }, [data.bars, s.i, p]);
  useEffect(() => { if (!s.pos && !s.pending) suggest(side); }, [s.i]); // eslint-disable-line react-hooks/exhaustive-deps

  const happened = useRef(false); // something happened on the latest step (a fill, a close, a cancelled order)
  const advance = useCallback((n = 1) => {
    setError(null);
    setS((cur) => {
      let next = cur;
      const msgs: string[] = [];
      for (let k = 0; k < n && !ended(m, next); k++) {
        next = step(m, next);
        msgs.push(...next.messages);
        if (next.messages.length && n > 1) break; // stop fast-forwarding when something happens
      }
      happened.current = msgs.length > 0;
      return { ...next, messages: msgs };
    });
  }, [m]);

  // Playing: one candle every 1/speed seconds, pausing when something happens or the replay ends.
  useEffect(() => {
    if (!playing) return;
    if (isEnd || happened.current) { happened.current = false; setPlaying(false); return; }
    const t = window.setTimeout(() => advance(1), 1000 / speed);
    return () => window.clearTimeout(t);
  }, [playing, s.i, speed, advance, isEnd]);

  // Keyboard: → or N for the next candle, Space to play or pause.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select") || finished) return;
      if (e.key === "ArrowRight" || e.key === "n") { e.preventDefault(); advance(1); }
      if (e.key === " ") { e.preventDefault(); happened.current = false; setPlaying((x) => !x); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [advance, finished]);

  // What the chart may show: candles up to now (or everything, once revealed).
  const upTo = revealed ? data.bars.length - 1 : s.i;
  const shown: ChartData = useMemo(() => {
    const cut = data.bars[upTo].time;
    return {
      ...data,
      bars: data.bars.slice(0, upTo + 1),
      indicators: data.indicators.map((ind) => ({ ...ind, lines: ind.lines.map((l) => ({ ...l, values: l.values.filter((v) => (v.time as number) <= cut) })) })),
      futureTimes: [],
    };
  }, [data, upTo]);

  const markers: ChartMarker[] = useMemo(() => {
    const out: ChartMarker[] = [{ time: data.bars[m.startIndex].time as Time, position: "aboveBar", shape: "square", color: "#fbbf24", text: "Start" }];
    for (const t of s.trades) {
      out.push({ time: t.entryTime as Time, position: t.side > 0 ? "belowBar" : "aboveBar", shape: t.side > 0 ? "arrowUp" : "arrowDown", color: "#93c5fd", text: "" });
      out.push({ time: t.exitTime as Time, position: t.side > 0 ? "aboveBar" : "belowBar", shape: "circle", color: t.pnl >= 0 ? "#34d399" : "#f87171",
        text: `${t.pnl >= 0 ? "+" : "−"}£${Math.abs(t.pnl).toFixed(2)}` });
    }
    return out.filter((x) => (x.time as number) <= data.bars[upTo].time).sort((a, b) => (a.time as number) - (b.time as number));
  }, [s.trades, data.bars, m.startIndex, upTo]);

  const shownTrade: ShownTrade | null = s.pos ? {
    id: 1, symbol: data.symbol.code, side: s.pos.side > 0 ? "long" : "short", entryPrice: s.pos.entryPrice, entryTime: s.pos.entryTime,
    stop: s.pos.stop, target: s.pos.target,
  } : null;

  const eq = equityNow(m, s);
  const result: Score | null = finished ? score(m, s) : null;

  function place() {
    const stop = Number(stopText);
    const target = useTarget && targetText ? Number(targetText) : null;
    const r = placeOrder(m, s, side, stop, target);
    if (typeof r === "string") setError(r); else { setS(r); setError(null); }
  }

  return (
    <div className="page replay">
      <div className="replay-chart">
        <div className="replay-bar">
          <b>{displayCode(data.symbol.code)}</b> <span className="muted">{data.symbol.name} · {data.timeframe}</span>
          <span className="replay-date">{dateOf(last.time, data.timeframe)}</span>
          <span className="muted">candle {s.i - m.startIndex} of {data.bars.length - 1 - m.startIndex}</span>
          {data.sample && <span className="tag stop">Sample data</span>}
        </div>
        <section className="chart-area">
          <ChartView data={shown} markers={markers} trade={revealed ? null : shownTrade} />
        </section>
      </div>

      <aside className="panel replay-panel" aria-label="Replay controls">
        {!finished ? (
          <>
            <div className="replay-controls">
              <button type="button" className="primary" disabled={isEnd} onClick={() => advance(1)} title="Next candle (→)">Next candle ▶</button>
              <button type="button" className="ghost" disabled={isEnd} onClick={() => advance(10)} title="Up to 10 candles, stopping if anything happens">+10 ▶▶</button>
              <button type="button" className="ghost" disabled={isEnd} onClick={() => { happened.current = false; setPlaying((x) => !x); }} title="Space">{playing ? "Pause ❚❚" : "Play"}</button>
              <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="Speed">
                {SPEEDS.map((x) => <option key={x} value={x}>{x} a second</option>)}
              </select>
            </div>
            <p className="muted small-text">→ next candle · Space play/pause. Playing pauses whenever a trade opens or closes.</p>

            <dl className="facts">
              <dt>Account</dt><dd>{money(eq)}</dd>
              <dt>Result so far</dt><dd className={eq - s.startBalance >= 0 ? "up" : "down"}>{money(eq - s.startBalance)}</dd>
            </dl>

            {s.messages.length > 0 && <ul className="warnings">{s.messages.map((x, i) => <li key={i} className="warn info">{x}</li>)}</ul>}

            {s.pos ? (
              <div className="replay-box">
                <h3>{s.pos.side > 0 ? "Buy" : "Short"} open <span className={openPnl(m, s) >= 0 ? "up" : "down"}>{money(openPnl(m, s))}</span></h3>
                <p className="muted small-text">Entry {s.pos.entryPrice.toFixed(p)} · risking {money(s.pos.riskGbp)}{s.pos.target !== null ? ` · target ${s.pos.target.toFixed(p)}` : ""}</p>
                <label className="form-row"><span className="field-label">Stop-loss</span>
                  <input type="number" step="any" defaultValue={s.pos.stop.toFixed(p)} key={s.pos.stop}
                    onBlur={(e) => {
                      const v = Number(e.target.value);
                      if (v === s.pos!.stop) return;
                      if ((s.pos!.stop - v) * s.pos!.side > 0 && !window.confirm("That moves the stop-loss further away, raising your risk. Go ahead?")) { e.target.value = s.pos!.stop.toFixed(p); return; }
                      const r = moveStop(s, v, last.close);
                      if (typeof r === "string") { setError(r); e.target.value = s.pos!.stop.toFixed(p); } else { setS(r); setError(null); }
                    }} /></label>
                <button type="button" className="ghost small" disabled={s.exitAsked || isEnd} onClick={() => setS({ ...s, exitAsked: true })}>
                  {s.exitAsked ? "Closing at the next open…" : "Close at the next open"}</button>
              </div>
            ) : s.pending ? (
              <div className="replay-box">
                <h3>{s.pending.side > 0 ? "Buy" : "Short"} order waiting</h3>
                <p className="muted small-text">Fills at the next candle's open. Stop {s.pending.stop.toFixed(p)}{s.pending.target !== null ? ` · target ${s.pending.target.toFixed(p)}` : ""}.</p>
                <button type="button" className="ghost small" onClick={() => setS({ ...s, pending: null })}>Cancel</button>
              </div>
            ) : (
              <div className="replay-box">
                <h3>Place a trade</h3>
                <div className="side-buttons">
                  <button type="button" className={`buy ${side > 0 ? "on" : ""}`} onClick={() => { setSide(1); suggest(1); }}>Buy</button>
                  <button type="button" className={`sell ${side < 0 ? "on" : ""}`} disabled={data.mode === "cash"} onClick={() => { setSide(-1); suggest(-1); }}>Sell (short)</button>
                </div>
                <div className="param-grid">
                  <label><span>Stop-loss</span><input type="number" step="any" value={stopText} onChange={(e) => setStopText(e.target.value)} /></label>
                  <label><span><input type="checkbox" checked={useTarget} onChange={(e) => setUseTarget(e.target.checked)} /> Target</span>
                    <input type="number" step="any" value={targetText} disabled={!useTarget} onChange={(e) => setTargetText(e.target.value)} /></label>
                </div>
                <p className="muted small-text">
                  Price {last.close.toFixed(p)}. Suggested stop: 2 × the typical candle range ({range.toFixed(p)}); target 2R.
                  Sized so a stop-out loses {risk}% of the account ({money((s.cash * risk) / 100)}).
                </p>
                <button type="button" className="primary" disabled={isEnd} onClick={place}>Place for the next open</button>
              </div>
            )}
            {error && <p className="warn stop">{error}</p>}

            {s.trades.length > 0 && (
              <div className="replay-trades">
                <h3>Trades ({s.trades.length})</h3>
                <ul>{[...s.trades].reverse().map((t, i) => (
                  <li key={i}><span className="muted">{dateOf(t.exitTime, data.timeframe)}</span> {t.side > 0 ? "Buy" : "Short"}{" "}
                    <b className={t.pnl >= 0 ? "up" : "down"}>{money(t.pnl)}</b>{t.r !== null && <span className="muted"> {t.r.toFixed(1)}R</span>}
                    <span className="muted"> · {t.reason}</span></li>
                ))}</ul>
              </div>
            )}

            <div className="planner-actions">
              <button type="button" className={isEnd ? "primary" : "ghost"} onClick={() => { setPlaying(false); setFinished(true); }}>
                {isEnd ? "See how you did" : "Finish here and score"}</button>
              <button type="button" className="link-button" onClick={() => { if (window.confirm("Leave this replay without saving it?")) onQuit(); }}>Leave</button>
            </div>
            {isEnd && s.pos && <p className="muted small-text">Your open trade is valued at the last close.</p>}
          </>
        ) : result && (
          <Results result={result} data={data} s={s} revealed={revealed} onReveal={() => setRevealed(true)}
            onAuthError={onAuthError} onQuit={onQuit} onAgain={onAgain} />
        )}
      </aside>
    </div>
  );
}

function Results({ result, data, s, revealed, onReveal, onAuthError, onQuit, onAgain }: {
  result: Score; data: ReplayData; s: ReplayState; revealed: boolean; onReveal: () => void;
  onAuthError: (err: unknown) => void; onQuit: () => void; onAgain: () => void;
}) {
  const [lesson, setLesson] = useState("");
  const [saved, setSaved] = useState(false);
  const savedOnce = useRef(false);
  const winRate = result.trades ? Math.round((result.wins / result.trades) * 100) : null;
  const beat = result.returnPct - result.buyHoldPct;

  function save(then?: () => void) {
    if (savedOnce.current) { then?.(); return; }
    api.replaySave({
      symbol: data.symbol.code, timeframe: data.timeframe, start_ts: data.bars[data.startIndex].time, end_ts: data.bars[s.i].time,
      candles: result.candles, trades: result.trades, wins: result.wins, net_gbp: round(result.net), return_pct: round(result.returnPct),
      buy_hold_pct: round(result.buyHoldPct), max_drawdown_pct: round(result.maxDrawdownPct), avg_r: result.avgR === null ? null : round(result.avgR),
      lesson: lesson.trim(),
    }).then(() => { savedOnce.current = true; setSaved(true); then?.(); }).catch(onAuthError);
  }

  return (
    <div className="replay-results">
      <h2>How you did</h2>
      <p className="muted small-text">{monthYear(data.bars[data.startIndex].time)} to {monthYear(data.bars[s.i].time)} · {result.candles} candles</p>
      <dl className="facts">
        <dt>Your result</dt><dd className={result.net >= 0 ? "up" : "down"}>{money(result.net)} ({pct(result.returnPct)})</dd>
        <dt>Simply holding</dt><dd className="muted">{pct(result.buyHoldPct)}</dd>
        <dt>Trades</dt><dd>{result.trades}{winRate !== null ? ` (${winRate}% won)` : ""}</dd>
        <dt>Average per trade</dt><dd>{result.avgR === null ? "–" : `${result.avgR.toFixed(2)}R`}</dd>
        <dt>Worst fall</dt><dd>{result.maxDrawdownPct.toFixed(1)}%</dd>
        {result.biggestWin !== null && <><dt>Best / worst trade</dt><dd>{money(result.biggestWin)} / {money(result.biggestLoss ?? 0)}</dd></>}
      </dl>
      <p className="note">
        {result.trades === 0 ? "No trades this time. Waiting is a skill too, but practice needs trades: try placing a few next time."
          : result.trades < 10 ? "Too few trades to judge skill from: one replay is practice, not proof. Look at whether you followed your plan."
          : beat > 0 ? `You beat simply holding by ${beat.toFixed(1)} points. Check your average R and worst fall: was it skill, or one big trade?`
          : `Holding did ${(-beat).toFixed(1)} points better. That's common; what would you do differently?`}
      </p>
      <label className="form-row"><span className="field-label">One lesson from this replay</span>
        <input maxLength={500} value={lesson} onChange={(e) => { setLesson(e.target.value); setSaved(false); savedOnce.current = false; }}
          placeholder="e.g. I closed winners too early; let the stop do its job" /></label>
      <div className="planner-actions">
        <button type="button" className="primary small" onClick={() => save()}>{saved ? "Saved ✓" : "Save to my replays"}</button>
        {!revealed && s.i < data.bars.length - 1 && <button type="button" className="ghost small" onClick={onReveal}>Show what happened next</button>}
      </div>
      <div className="planner-actions">
        <button type="button" className="ghost small" onClick={() => save(onAgain)}>Save and replay again</button>
        <button type="button" className="link-button" onClick={() => save(onQuit)}>Save and finish</button>
      </div>
    </div>
  );
}

const round = (v: number) => Math.round(v * 100) / 100;
