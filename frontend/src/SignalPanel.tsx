import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { money } from "./BacktestPage";
import type { SignalCard, SignalSide, SignalsResponse } from "./types";

const STATUS_TEXT: Record<string, string> = {
  complete: "Setup complete",
  forming: "Watch: forming",
  in_trade: "In a trade",
  none: "No setup",
};
const SETTINGS_KEY = "gt.signals.v1";

function loadSettings(): { balance: number; risk: number } {
  try {
    return { balance: 200, risk: 1, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") };
  } catch {
    return { balance: 200, risk: 1 };
  }
}

const when = (t: number) => new Date(t * 1000).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const fmt = (v: number, p: number) => v.toFixed(Math.min(6, Math.max(2, p)));

interface Props {
  symbol: string;
  timeframe: string;
  lastBarTime: number | undefined; // refreshes when a new candle appears
  precision: number;
  onBacktest: (strategy: string) => void;
  onAuthError: (err: unknown) => void;
}

/** What each strategy's rules say about the chart on screen: rule checks and past results, not advice. */
export default function SignalPanel({ symbol, timeframe, lastBarTime, precision, onBacktest, onAuthError }: Props) {
  const [settings, setSettings] = useState(loadSettings);
  const [data, setData] = useState<SignalsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const first = useRef(true);

  useEffect(() => {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch {
      /* ignore */
    }
  }, [settings]);

  useEffect(() => {
    const background = !first.current;
    first.current = false;
    setLoading(true);
    const timer = window.setTimeout(() => {
      api
        .signals(symbol, timeframe, settings.balance, settings.risk, background)
        .then((d) => {
          setData(d);
          setError(null);
        })
        .catch((err) => {
          if (err instanceof ApiError && err.status === 401) onAuthError(err);
          else setError(err instanceof Error ? err.message : "Couldn't check the signals.");
        })
        .finally(() => setLoading(false));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [symbol, timeframe, lastBarTime, settings, onAuthError]);

  useEffect(() => {
    first.current = true;
    setData(null);
    setOpen(null);
  }, [symbol, timeframe]);

  const stale = data && (data.symbol.code !== symbol || data.timeframe !== timeframe);

  return (
    <div className="signals">
      <h2>Signal assistant</h2>
      <p className="muted small-text">
        Checks each strategy's rules on the last finished candle and shows how the same rules did here in the past.
        It shows rules and history, not advice.
      </p>
      <div className="param-grid compact">
        <label><span>Account (£)</span>
          <input type="number" min={1} step="any" value={settings.balance}
            onChange={(e) => setSettings((s) => ({ ...s, balance: Math.max(1, Number(e.target.value) || 200) }))} /></label>
        <label><span>Risk (%)</span>
          <input type="number" min={0.1} max={2} step="any" value={settings.risk}
            onChange={(e) => setSettings((s) => ({ ...s, risk: Math.min(2, Math.max(0.1, Number(e.target.value) || 1)) }))} /></label>
      </div>

      {error && <p className="warn stop">{error}</p>}
      {loading && !data && <p className="muted">Checking the rules… (the first time on a market downloads its history)</p>}

      {data && !stale && (
        <>
          <p className="muted small-text">
            Candle closed {when(data.candleClosed)} · {data.mode === "cash" ? "real shares, long only" : "CFD/spread bet, long and short"} · {data.years} years of history
          </p>
          {data.sample && <p className="warn stop">Sample data, not real prices: these checks mean nothing yet.</p>}
          <ul className="signal-list">
            {data.strategies.map((c) => (
              <Card key={c.key} card={c} precision={precision} expanded={open === c.key}
                onToggle={() => setOpen(open === c.key ? null : c.key)} onBacktest={() => onBacktest(c.key)} />
            ))}
          </ul>
          <p className="muted small-text">
            Buy and hold here: {data.buyHold.returnPct > 0 ? "+" : ""}{data.buyHold.returnPct.toFixed(1)}% over the same history.
            Past results don't predict future ones; a complete setup is not a reason on its own to trade.
          </p>
        </>
      )}
    </div>
  );
}

function Card({ card, precision, expanded, onToggle, onBacktest }: {
  card: SignalCard; precision: number; expanded: boolean; onToggle: () => void; onBacktest: () => void;
}) {
  const s = card.best;
  const h = card.history;
  return (
    <li className={`signal ${card.status}`}>
      <button type="button" className="signal-head" onClick={onToggle} aria-expanded={expanded}>
        <span className="signal-name">{card.name}</span>
        <span className={`status-pill ${card.status}`}>
          {STATUS_TEXT[card.status]}{card.status !== "none" && card.status !== "in_trade" ? ` · ${s.side === "long" ? "buy" : "short"}` : ""}
        </span>
        <span className="signal-meter" aria-label={`${s.met} of ${s.total} conditions met`}>
          {s.checks.map((c, i) => <i key={i} className={c.ok ? "ok" : ""} />)}
        </span>
      </button>

      {expanded && (
        <div className="signal-body">
          {card.openTrade && (
            <p className="note">
              These rules have been in a {card.openTrade.side === "long" ? "buy" : "short"} since {when(card.openTrade.since)} at {fmt(card.openTrade.entry, precision)},
              stop-loss {fmt(card.openTrade.stop, precision)}. Exit rule: {card.openTrade.exitRule}.
            </p>
          )}
          {card.sides.map((side) => <SideView key={side.side} side={side} precision={precision} showSide={card.sides.length > 1} />)}
          <p className="evidence">
            <b>On this market and timeframe:</b> {h.trades} trades over {h.years} years, {h.returnPct > 0 ? "+" : ""}{h.returnPct.toFixed(1)}% after costs
            {h.winRate !== null && <>, {h.winRate.toFixed(0)}% won</>}, worst fall {h.maxDrawdownPct.toFixed(0)}%.{" "}
            {h.beatsBuyHold ? "Beat buy and hold." : "Did not beat buy and hold."}
            {h.trades < 30 && " Too few trades to trust."}
          </p>
          <button type="button" className="ghost small" onClick={onBacktest}>Open full backtest</button>
        </div>
      )}
    </li>
  );
}

function SideView({ side, precision, showSide }: { side: SignalSide; precision: number; showSide: boolean }) {
  const e = side.evidence;
  return (
    <div className="side-view">
      {showSide && <h4>{side.side === "long" ? "Buy side" : "Short side"} · {side.met}/{side.total}</h4>}
      <ul className="checks">
        {side.checks.map((c, i) => (
          <li key={i} className={c.ok ? "ok" : ""}><span aria-hidden="true">{c.ok ? "✓" : "○"}</span> {c.label}</li>
        ))}
      </ul>
      <p className="reason">{side.reason}</p>
      {e.trades > 0 && (
        <p className="muted small-text">
          Past {side.side === "long" ? "buy" : "short"} signals here: {e.trades}, {e.winRate?.toFixed(0)}% won, average {e.avgR !== null && e.avgR > 0 ? "+" : ""}{e.avgR?.toFixed(2)}R{e.lowSample ? " (small sample)" : ""}.
        </p>
      )}
      {side.plan && (
        <dl className="facts plan">
          <dt>{side.status === "complete" ? "Rules' entry (next open, about)" : "If it completes, entry about"}</dt><dd>{fmt(side.plan.entry, precision)}</dd>
          <dt>Stop-loss ({side.plan.stopRule})</dt><dd>{fmt(side.plan.stop, precision)}</dd>
          <dt>Size from the risk guard</dt><dd>{side.plan.units < 10 ? side.plan.units.toFixed(3) : Math.floor(side.plan.units).toLocaleString("en-GB")}</dd>
          <dt>Lose if stopped out</dt><dd>{money(side.plan.riskGbp)}</dd>
          <dt>Position value</dt><dd>{money(side.plan.valueGbp)}</dd>
          <dt>Exit rule</dt><dd className="text">{side.plan.exitRule}</dd>
        </dl>
      )}
      {side.plan?.note && <p className="muted small-text">{side.plan.note}</p>}
    </div>
  );
}
