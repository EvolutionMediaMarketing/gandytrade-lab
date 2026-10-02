import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { money } from "./BacktestPage";
import { displayCode } from "./MarketPicker";
import type { TradePlan } from "./PlanZones";
import type { PositionSize, SymbolInfo } from "./types";

const SETTINGS_KEY = "gt.plan.v1";
type Mode = "" | "cash" | "cfd";

function loadSettings(): { balance: number; risk: number; mode: Mode } {
  try {
    return { balance: 200, risk: 1, mode: "", ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") };
  } catch {
    return { balance: 200, risk: 1, mode: "" };
  }
}

export const CASH_CLASSES = ["stock", "etf", "ukstock"];

interface Props {
  symbol: SymbolInfo;
  plan: TradePlan | null;
  onPlanChange: (plan: TradePlan | null) => void;
  onStartFresh: () => void;
  onAuthError: (err: unknown) => void;
}

/** Plan a trade on the chart: drag the lines, see the size, the risk and the reward in pounds. */
export default function TradePlanner({ symbol, plan, onPlanChange, onStartFresh, onAuthError }: Props) {
  const [settings, setSettings] = useState(loadSettings);
  const [out, setOut] = useState<PositionSize | null>(null);
  const [error, setError] = useState<string | null>(null);
  const p = symbol.precision;
  const mode: "cash" | "cfd" = settings.mode || (CASH_CLASSES.includes(symbol.asset_class) ? "cash" : "cfd");
  const side = plan ? (plan.stop < plan.entry ? "long" : "short") : "long";

  useEffect(() => {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch {
      /* ignore */
    }
  }, [settings]);

  // Size the trade with the risk guard; a short pause so dragging doesn't send a request per pixel.
  useEffect(() => {
    if (!plan || plan.entry === plan.stop) {
      setOut(null);
      return;
    }
    const timer = window.setTimeout(() => {
      api
        .positionSize({ symbol: symbol.code, balance: settings.balance, risk_pct: settings.risk, entry: plan.entry, stop: plan.stop, mode })
        .then((r) => {
          setOut(r);
          setError(null);
        })
        .catch((err) => {
          if (err instanceof ApiError && err.status === 401) onAuthError(err);
          setOut(null);
          setError(err instanceof Error ? err.message : "Couldn't size this trade.");
        });
    }, 200);
    return () => window.clearTimeout(timer);
  }, [plan, settings, mode, symbol.code, onAuthError]);

  if (!plan) return <p className="muted">Getting the latest price…</p>;

  const set = (key: keyof TradePlan, value: string) => {
    const v = value === "" ? null : Number(value);
    if (key === "target") onPlanChange({ ...plan, target: v !== null && Number.isFinite(v) ? v : null });
    else if (v !== null && Number.isFinite(v) && v > 0) onPlanChange({ ...plan, [key]: v });
  };

  const risk = Math.abs(plan.entry - plan.stop);
  const targetOk = plan.target !== null && (plan.target - plan.entry) * (side === "long" ? 1 : -1) > 0;
  const rMultiple = targetOk && risk > 0 ? Math.abs(plan.target! - plan.entry) / risk : null;
  const gainGbp = out && targetOk ? out.units * Math.abs(plan.target! - plan.entry) / out.perGbp : null;
  const breakEven = rMultiple ? 100 / (1 + rMultiple) : null;
  const cashShort = mode === "cash" && side === "short";

  function flip() {
    const d = plan!.entry - plan!.stop;
    const t = plan!.target === null ? null : plan!.entry - (plan!.target - plan!.entry);
    onPlanChange({ entry: plan!.entry, stop: plan!.entry + d, target: t });
  }

  return (
    <div className="planner">
      <h2>Plan a trade</h2>
      <p className="muted small-text">
        Drag the <span className="k entry">entry</span>, <span className="k stop">stop-loss</span> and <span className="k target">target</span> lines on the chart, or type prices below.
        Nothing is traded.
      </p>

      <div className="segmented wide" role="radiogroup" aria-label="Account type">
        <button type="button" className={mode === "cash" ? "on" : ""} onClick={() => setSettings((s) => ({ ...s, mode: "cash" }))}>Real shares</button>
        <button type="button" className={mode === "cfd" ? "on" : ""} onClick={() => setSettings((s) => ({ ...s, mode: "cfd" }))}>CFD / spread bet</button>
      </div>

      <div className="param-grid">
        <label><span>Entry</span><PriceInput value={plan.entry} precision={p} onCommit={(v) => set("entry", v)} /></label>
        <label><span>Stop-loss</span><PriceInput value={plan.stop} precision={p} onCommit={(v) => set("stop", v)} /></label>
        <label><span>Target (optional)</span><PriceInput value={plan.target} precision={p} onCommit={(v) => set("target", v)} /></label>
        <label><span>Account (£)</span><input type="number" min={1} step="any" value={settings.balance}
          onChange={(e) => setSettings((s) => ({ ...s, balance: Math.max(1, Number(e.target.value) || 200) }))} /></label>
        <label><span>Risk per trade (%)</span><input type="number" min={0.1} max={2} step="any" value={settings.risk}
          onChange={(e) => setSettings((s) => ({ ...s, risk: Math.min(2, Math.max(0.1, Number(e.target.value) || 1)) }))} /></label>
      </div>

      <div className="planner-actions">
        <button type="button" className="ghost small" onClick={onStartFresh}>Start from latest price</button>
        {mode === "cfd" && <button type="button" className="ghost small" onClick={flip}>{side === "long" ? "Make it a short" : "Make it a buy"}</button>}
        {plan.target === null
          ? <button type="button" className="ghost small" onClick={() => onPlanChange({ ...plan, target: plan.entry + 2 * (plan.entry - plan.stop) })}>Add a 2R target</button>
          : <button type="button" className="ghost small" onClick={() => onPlanChange({ ...plan, target: null })}>Remove target</button>}
      </div>

      {cashShort && <p className="warn caution">With real shares you can only buy, so the stop-loss must be below the entry. Switch to CFD / spread bet to plan a short.</p>}
      {error && !cashShort && <p className="warn stop">{error}</p>}

      {out && !cashShort && (
        <div className="tool-result">
          <p className="big">
            {side === "long" ? "Buy" : "Short"} <b>{out.units < 10 ? out.units.toFixed(4) : Math.floor(out.units).toLocaleString("en-GB")}</b>{" "}
            {CASH_CLASSES.includes(symbol.asset_class) ? "shares" : "units"} of {displayCode(symbol.code)}
          </p>
          <dl className="facts">
            <dt>Lose if the stop is hit</dt><dd className="down">{money(-out.riskGbp)}</dd>
            {gainGbp !== null && <><dt>Gain if the target is hit</dt><dd className="up">{money(gainGbp)}</dd></>}
            <dt>Typical costs (in and out)</dt><dd>{money(out.costGbp)}</dd>
            <dt>Position value</dt><dd>{money(out.valueGbp)}</dd>
            {out.marginGbp !== null && <><dt>Margin held by the broker</dt><dd>{money(out.marginGbp)}</dd></>}
          </dl>
          {rMultiple !== null && breakEven !== null && (
            <p className="note">
              Reward is <b>{rMultiple.toFixed(1)}×</b> the risk ({rMultiple.toFixed(1)}R). Trades like this come out ahead only if more than{" "}
              <b>{breakEven.toFixed(0)}%</b> of them reach the target, before costs.
            </p>
          )}
          {plan.target !== null && !targetOk && <p className="warn caution">The target is on the wrong side of the entry.</p>}
          {out.capped && <p className="warn caution">{out.note}</p>}
          {symbol.asset_class === "ukstock" && <p className="muted small-text">Prices in pence. Many UK platforms only sell whole shares: round down.</p>}
        </div>
      )}

      <button type="button" className="primary" disabled title="Arrives with paper trading in Phase 3">
        Place on paper account (coming in Phase 3)
      </button>
      <p className="muted small-text">When paper trading arrives, this places the plan in your pretend-money account and tracks it against live prices.</p>
    </div>
  );
}

/** A price box that follows the chart while you drag, and applies what you type when you press Enter or leave it. */
function PriceInput({ value, precision, onCommit }: { value: number | null; precision: number; onCommit: (v: string) => void }) {
  const [text, setText] = useState(value === null ? "" : value.toFixed(precision));
  const editing = useRef(false);
  useEffect(() => {
    if (!editing.current) setText(value === null ? "" : value.toFixed(precision));
  }, [value, precision]);
  const commit = () => {
    editing.current = false;
    onCommit(text.trim());
  };
  return (
    <input type="number" step="any" value={text}
      onFocus={() => { editing.current = true; }}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
  );
}
