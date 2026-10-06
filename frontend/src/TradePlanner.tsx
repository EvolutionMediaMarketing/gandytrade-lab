import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { money } from "./BacktestPage";
import { displayCode } from "./MarketPicker";
import type { TradePlan } from "./PlanZones";
import type { CalendarEvent, OddsRow, PaperAccount, PositionSize, PriceOrder, SymbolInfo, TargetOdds } from "./types";
import { inWords } from "./CalendarPanel";

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
  timeframe: string;
  onPlaced: () => void;
  plan: TradePlan | null;
  onPlanChange: (plan: TradePlan | null) => void;
  onStartFresh: (side: "long" | "short") => void;
  onAuthError: (err: unknown) => void;
  /** The latest price on the chart, to tell whether a price order buys a rise or a dip. */
  lastPrice?: number | null;
  /** Paper price orders waiting on this market. */
  orders?: PriceOrder[];
  onOrdersChanged?: () => void;
  /** A high-impact event for this market within 24 hours, if any. */
  eventSoon?: CalendarEvent | null;
  /** Stop-loss and target move with the entry line. */
  linked?: boolean;
  onLinkedChange?: (on: boolean) => void;
}

/** Plan a trade on the chart: drag the lines, see the size, the risk and the reward in pounds. */
export default function TradePlanner({ symbol, timeframe, onPlaced, plan, onPlanChange, onStartFresh, onAuthError, lastPrice = null,
  orders = [], onOrdersChanged, linked = true, onLinkedChange, eventSoon = null }: Props) {
  // The typical daily move (ATR), to describe stop distances in a way that means something.
  const [dailyAtr, setDailyAtr] = useState<number | null>(null);
  useEffect(() => {
    setDailyAtr(null);
    api.quote(symbol.code).then((q) => setDailyAtr(q.dailyAtr)).catch(() => undefined);
  }, [symbol.code]);
  const [settings, setSettings] = useState(loadSettings);
  const [accounts, setAccounts] = useState<PaperAccount[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);

  useEffect(() => {
    api.paperAccounts().then((r) => setAccounts(r.accounts.filter((a) => !a.archived))).catch(onAuthError);
  }, [onAuthError]);

  // Sizing follows the chosen paper account: its balance, risk setting and account type.
  const account = accounts.find((a) => a.id === accountId) ?? null;
  useEffect(() => {
    if (account) setSettings((s) => ({ ...s, balance: account.equity, risk: account.riskPct, mode: account.mode }));
  }, [account]);
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
    if (!plan || plan.entry === plan.stop || plan.stop <= 0 || Math.abs(plan.entry - plan.stop) > plan.entry * 0.5) {
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
  const planProblem =
    plan.stop <= 0 ? "The stop-loss must be above zero."
    : risk > plan.entry * 0.5 ? "The stop-loss is more than half the price away from the entry. Drag it closer, or press Buy or Sell to start again."
    : plan.target !== null && plan.target <= 0 ? "The target must be above zero."
    : "";
  const targetOk = plan.target !== null && (plan.target - plan.entry) * (side === "long" ? 1 : -1) > 0;
  const rMultiple = targetOk && risk > 0 ? Math.abs(plan.target! - plan.entry) / risk : null;
  const gainGbp = out && targetOk ? out.units * Math.abs(plan.target! - plan.entry) / out.perGbp : null;
  const breakEven = rMultiple ? 100 / (1 + rMultiple) : null;
  const cashShort = mode === "cash" && side === "short";

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

      <div className="side-buttons" role="radiogroup" aria-label="Buy or sell">
        <button type="button" className={`buy ${side === "long" ? "on" : ""}`} aria-pressed={side === "long"} onClick={() => onStartFresh("long")}
          title="Bet on the price rising. Sets the stop-loss below the price, sized by your safeguards.">
          Buy
        </button>
        <button type="button" className={`sell ${side === "short" ? "on" : ""}`} aria-pressed={side === "short"} disabled={mode === "cash"}
          onClick={() => onStartFresh("short")}
          title={mode === "cash" ? "With real shares you can only buy." : "Bet on the price falling (short). Sets the stop-loss above the price."}>
          Sell (short)
        </button>
      </div>
      <p className="muted small-text">
        Pressing one sets the entry at the latest price, the stop-loss 2 × the typical daily move on the safe side and a 2R target,
        sized so a stop-out loses {settings.risk}% of the account. Drag the lines to adjust.
      </p>

      <div className="param-grid">
        <label><span>Entry</span><PriceInput value={plan.entry} precision={p} onCommit={(v) => set("entry", v)} /></label>
        <label><span>Stop-loss</span><PriceInput value={plan.stop} precision={p} onCommit={(v) => set("stop", v)} /></label>
        <label title="Take-profit: the trade closes automatically when the price reaches this level."><span>Target / take-profit (optional)</span><PriceInput value={plan.target} precision={p} onCommit={(v) => set("target", v)} /></label>
        <label><span>Account (£)</span><input type="number" min={1} step="any" value={settings.balance}
          onChange={(e) => setSettings((s) => ({ ...s, balance: Math.max(1, Number(e.target.value) || 200) }))} /></label>
        <label><span>Risk per trade (%)</span><input type="number" min={0.1} max={2} step="any" value={settings.risk}
          onChange={(e) => setSettings((s) => ({ ...s, risk: Math.min(2, Math.max(0.1, Number(e.target.value) || 1)) }))} /></label>
      </div>

      <label className="check-row" title="Drag or type the entry and the stop-loss and target keep the same distances, so the risk stays as planned.">
        <input type="checkbox" checked={linked} onChange={(e) => onLinkedChange?.(e.target.checked)} />
        Stop-loss and target move with the entry
      </label>
      {dailyAtr !== null && risk > 0 && (
        <p className="muted small-text">
          Stop distance: {risk.toFixed(p)}, about <b>{(risk / dailyAtr).toFixed(1)} ×</b> the typical daily move ({dailyAtr.toFixed(p)}).
          {risk / dailyAtr < 1 ? " That's tight: ordinary day-to-day wobbles often reach it." : risk / dailyAtr > 4 ? " That's wide: the trade will be small to keep the risk to plan." : " A sensible range is 1.5 to 3 ×."}
        </p>
      )}

      <div className="planner-actions">
        <button type="button" className="ghost small" onClick={() => onStartFresh(side)}>Start again from latest price</button>
        {plan.target === null
          ? <button type="button" className="ghost small" onClick={() => {
              const t = plan.entry + 2 * (plan.entry - plan.stop);
              onPlanChange({ ...plan, target: t > 0 ? t : null });
            }}>Add a 2R target</button>
          : <button type="button" className="ghost small" onClick={() => onPlanChange({ ...plan, target: null })}>Remove target</button>}
      </div>

      {eventSoon && (
        <p className="warn caution">
          <b>{eventSoon.title}</b> {inWords(eventSoon.inSeconds)}. Around big announcements prices can jump past a stop-loss and spreads widen,
          so a trade can lose more than planned. Many traders wait until it's out.
        </p>
      )}
      {planProblem && <p className="warn stop">{planProblem}</p>}
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
            <dd className="facts-note muted">
              {out.capped ? "Less than your risk setting: see the note below." :
                `Stays at your ${settings.risk}% risk wherever the stop goes; moving the stop changes the number of ${CASH_CLASSES.includes(symbol.asset_class) ? "shares" : "units"} instead.`}
            </dd>
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

      {!cashShort && !planProblem && plan.entry !== plan.stop && (
        <OddsBox symbol={symbol} timeframe={timeframe} plan={plan} mode={mode} precision={p}
          onUseTarget={(price) => onPlanChange({ ...plan, target: Number(price.toFixed(p)) })} onAuthError={onAuthError} />
      )}

      <Checkout
        accounts={accounts} accountId={accountId} onAccount={setAccountId} symbol={symbol} timeframe={timeframe}
        plan={plan} side={side} out={out} cashShort={cashShort} lastPrice={lastPrice} dailyAtr={dailyAtr}
        onPlaced={() => {
          api.paperAccounts().then((r) => setAccounts(r.accounts.filter((a) => !a.archived))).catch(() => undefined);
          onPlaced();
        }}
        onAuthError={onAuthError}
      />

      {orders.length > 0 && (
        <WaitingOrders orders={orders} accounts={accounts} precision={p} onChanged={() => onOrdersChanged?.()} onAuthError={onAuthError} />
      )}
    </div>
  );
}

/** Which kind of price order an entry line makes, given where the price is now. */
export function orderKind(side: "long" | "short", entry: number, last: number | null): { kind: string; explain: string } | null {
  if (last === null || !Number.isFinite(last) || Math.abs(entry - last) <= last * 1e-6) return null;
  const up = entry > last;
  if (side === "long") {
    return up
      ? { kind: "Buy stop", explain: "buys if the price rises to your entry: for catching a breakout" }
      : { kind: "Buy limit", explain: "buys if the price falls to your entry: for buying a dip" };
  }
  return up
    ? { kind: "Sell limit", explain: "sells short if the price rises to your entry: for selling into a bounce" }
    : { kind: "Sell stop", explain: "sells short if the price falls to your entry: for catching a breakdown" };
}

const EXPIRIES = [
  ["gtc", "Until I cancel it"], ["day", "End of today (10pm UK)"], ["week", "End of this week (Friday 10pm UK)"], ["month", "In 30 days"],
];

/** Price orders waiting on this market, with a way to cancel each. */
function WaitingOrders({ orders, accounts, precision, onChanged, onAuthError }: {
  orders: PriceOrder[]; accounts: PaperAccount[]; precision: number; onChanged: () => void; onAuthError: (err: unknown) => void;
}) {
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const name = (id: number) => accounts.find((a) => a.id === id)?.name ?? "Paper account";
  return (
    <div className="waiting-orders">
      <h3>Waiting price orders <span className="muted small-text">(dotted lines on the chart)</span></h3>
      <ul>
        {orders.map((o) => (
          <li key={o.id}>
            <span><b>{o.kind}</b> at <span className="mono">{o.level.toFixed(precision)}</span> · stop <span className="mono">{o.stop.toFixed(precision)}</span>
              {o.target !== null && <> · target <span className="mono">{o.target.toFixed(precision)}</span></>}
              <br /><span className="muted small-text">{name(o.accountId)}{o.expiresAt
                ? ` · expires ${new Date(o.expiresAt).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}`
                : " · until cancelled"}</span></span>
            <button type="button" className="ghost small" disabled={busy === o.id}
              onClick={() => {
                setBusy(o.id);
                setError(null);
                api.cancelPriceOrder(o.id).then(onChanged)
                  .catch((err) => { onAuthError(err); setError(err instanceof Error ? err.message : "Couldn't cancel it."); onChanged(); })
                  .finally(() => setBusy(null));
              }}>Cancel</button>
          </li>
        ))}
      </ul>
      {error && <p className="warn stop">{error}</p>}
    </div>
  );
}

const MOODS = [
  ["calm", "Calm"], ["confident", "Confident"], ["unsure", "Unsure"], ["anxious", "Anxious"],
  ["bored", "Bored"], ["fomo", "Fear of missing out"], ["frustrated", "Frustrated"],
];

/** The pre-trade checklist. The order can't be placed until every item is done. */
function Checkout({ accounts, accountId, onAccount, symbol, timeframe, plan, side, out, cashShort, lastPrice, dailyAtr, onPlaced, onAuthError }: {
  accounts: PaperAccount[]; accountId: number | null; onAccount: (id: number | null) => void; symbol: SymbolInfo;
  timeframe: string; plan: TradePlan; side: "long" | "short"; out: PositionSize | null; cashShort: boolean;
  lastPrice: number | null; dailyAtr: number | null; onPlaced: () => void; onAuthError: (err: unknown) => void;
}) {
  const [when, setWhen] = useState<"now" | "level" | "open">("now");
  // Trailing stop: off by default; its distance starts as the planned stop distance until you type your own.
  const [trailOn, setTrailOn] = useState(false);
  const [trailText, setTrailText] = useState("");
  const trailEdited = useRef(false);
  const planned = Math.abs(plan.entry - plan.stop);
  useEffect(() => {
    if (!trailEdited.current) setTrailText(planned > 0 ? planned.toFixed(symbol.precision) : "");
  }, [planned, symbol.precision]);
  const trailDistance = trailOn ? Number(trailText) : null;
  const trailOk = !trailOn || (Number.isFinite(trailDistance) && (trailDistance ?? 0) > 0 && (trailDistance ?? 0) < plan.entry * 0.5);
  const [expiry, setExpiry] = useState("gtc");
  const priced = orderKind(side, plan.entry, lastPrice);
  const atLevel = when === "level";
  const atOpen = when === "open";
  const [open, setOpen] = useState(false);
  const [trend, setTrend] = useState("");
  const [reason, setReason] = useState("");
  const [mood, setMood] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const account = accounts.find((a) => a.id === accountId) ?? null;

  useEffect(() => {
    setConfirmed(false); // any change to the plan needs a fresh look
  }, [plan.entry, plan.stop, plan.target, accountId, when]);

  const against = (side === "long" && trend === "down") || (side === "short" && trend === "up");
  const checks = [
    { ok: !!account, text: "Paper account chosen" },
    { ok: !!trend, text: "Trend direction noted" },
    { ok: plan.stop > 0, text: "Stop-loss set" },
    { ok: reason.trim().length >= 10, text: "One-sentence reason written" },
    { ok: confirmed, text: "Size and £ at risk checked" },
  ];
  const ready = checks.every((c) => c.ok) && !!out && !cashShort && !account?.block && (!atLevel || !!priced) && trailOk;

  function place() {
    if (!account) return;
    setBusy(true);
    setError(null);
    if ((atLevel && priced) || atOpen) {
      api
        .placePriceOrder({
          account_id: account.id, symbol: symbol.code, side, level: plan.entry, stop: plan.stop, target: plan.target, timeframe,
          trend, reason: reason.trim(), mood, confirmed, expiry: atOpen ? "week" : expiry, trail_distance: trailDistance,
          at_open: atOpen,
        })
        .then((o) => {
          setDone(atOpen
            ? `${o.kind} order placed on “${account.name}”. It fills at the first live price when the market opens, sized on ` +
              "the account then. If the price opens past your stop-loss, it's cancelled and you'll get an alert."
            : `${o.kind} order placed on “${account.name}” at ${o.level.toFixed(symbol.precision)}. The worker checks it every minute ` +
              "and opens the trade when the price gets there, through the account's safeguards. It's the dotted line on the chart.");
          setReason("");
          setTrend("");
          setMood("");
          setConfirmed(false);
          setOpen(false);
          onPlaced();
        })
        .catch((err) => {
          onAuthError(err);
          setError(err instanceof Error ? err.message : "The order wasn't placed.");
        })
        .finally(() => setBusy(false));
      return;
    }
    api
      .placePaperTrade({
        account_id: account.id, symbol: symbol.code, side, stop: plan.stop, target: plan.target, timeframe,
        trend, reason: reason.trim(), mood, confirmed, trail_distance: trailDistance,
      })
      .then((r) => {
        setDone(`Placed on “${account.name}”: ${side === "long" ? "bought" : "shorted"} at ${r.trade.entryPrice.toFixed(symbol.precision)}. ` +
          "The worker now watches its stop-loss and target. Find it on the Paper page.");
        setReason("");
        setTrend("");
        setMood("");
        setConfirmed(false);
        setOpen(false);
        onPlaced();
      })
      .catch((err) => {
        onAuthError(err);
        setError(err instanceof Error ? err.message : "The order wasn't placed.");
      })
      .finally(() => setBusy(false));
  }

  if (!open) {
    return (
      <>
        {done && <p className="note">{done}</p>}
        <button type="button" className="primary" onClick={() => { setOpen(true); setDone(null); }}>Place on a paper account…</button>
        <p className="muted small-text">Pretend money on live prices. A short checklist comes first.</p>
      </>
    );
  }

  return (
    <div className="checkout">
      <h3>Before you place it</h3>
      <label className="form-row">
        <span className="field-label">Paper account</span>
        <select value={accountId ?? ""} onChange={(e) => onAccount(e.target.value ? Number(e.target.value) : null)}>
          <option value="">Choose…</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} · {money(a.equity)} · {a.mode === "cash" ? "real shares" : "CFD"}
            </option>
          ))}
        </select>
      </label>
      {account?.block && <p className="warn stop">{account.block}</p>}

      <div className="form-row">
        <span className="field-label">When</span>
        <div className="segmented wide" role="radiogroup" aria-label="When to trade">
          <button type="button" className={!atLevel ? "on" : ""} onClick={() => setWhen("now")}>Now, at the live price</button>
          <button type="button" className={atLevel ? "on" : ""} onClick={() => setWhen("level")}>When the price reaches my entry</button>
          <button type="button" className={atOpen ? "on" : ""} onClick={() => setWhen("open")}
            title="For a closed market: fill at the first live price when it opens">When the market opens</button>
        </div>
        {atOpen && (
          <p className="note">
            For when the market is closed. It fills at the <b>opening price</b>, which can be some way from the last price because
            of overnight news. The size is worked out then, so the risk stays at your setting; if the price opens past your
            stop-loss, nothing is traded and you'll get an alert. Lapses after a week if not filled.
          </p>
        )}
        {atLevel && (priced ? (
          <p className="note">
            <b>{priced.kind}</b> at {plan.entry.toFixed(symbol.precision)}: {priced.explain}
            {lastPrice !== null && <> (the price is {lastPrice.toFixed(symbol.precision)} now)</>}. Drag the entry line to change it.
          </p>
        ) : (
          <p className="warn caution">Your entry is at the current price. Drag the entry line to the level you want, or trade now.</p>
        ))}
        {atLevel && priced && (
          <label className="form-row">
            <span className="field-label">Expires</span>
            <select value={expiry} onChange={(e) => setExpiry(e.target.value)}>
              {EXPIRIES.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
          </label>
        )}
      </div>
      {account && !account.block && (
        <p className="muted small-text">
          At risk now on this account: {money(account.openRisk)} of {money(account.openRiskLimit)} allowed ({account.maxOpenRiskPct}%).
          {account.openRiskLimit - account.openRisk < (out?.riskGbp ?? 0) && " This trade will be trimmed to fit, or refused if there's no room."}
        </p>
      )}

      <div className="form-row">
        <span className="field-label">Stop-loss</span>
        <div className="segmented wide" role="radiogroup" aria-label="Stop-loss type">
          <button type="button" className={!trailOn ? "on" : ""} onClick={() => setTrailOn(false)}>Fixed</button>
          <button type="button" className={trailOn ? "on" : ""} onClick={() => setTrailOn(true)}>Trailing</button>
        </div>
        {trailOn && (
          <>
            <label className="form-row">
              <span className="field-label">Follows this far behind the price</span>
              <input type="number" step="any" min={0} value={trailText}
                onChange={(e) => { trailEdited.current = true; setTrailText(e.target.value); }} />
            </label>
            <p className="muted small-text">
              The stop starts at your stop-loss line, then follows the best price since the trade opened, {trailDistance && trailDistance > 0
                ? <>{trailDistance.toFixed(symbol.precision)}{dailyAtr ? <> (about {(trailDistance / dailyAtr).toFixed(1)} × the typical daily move)</> : null}</>
                : "this far"} behind it. It only ever tightens, so it locks in profit as the price moves your way.
              {" "}2 to 3 × the daily move is sensible; much closer and ordinary wobbles stop you out early. If you later set the stop
              yourself, the trailing stop is cancelled (you'll be warned first).
            </p>
            {!trailOk && <p className="warn stop">Set a trailing distance above zero and less than half the price.</p>}
          </>
        )}
      </div>

      <div className="form-row">
        <span className="field-label">Which way is the market trending on this chart?</span>
        <div className="segmented wide" role="radiogroup" aria-label="Trend">
          {[["up", "Up"], ["sideways", "Sideways"], ["down", "Down"]].map(([k, label]) => (
            <button key={k} type="button" className={trend === k ? "on" : ""} onClick={() => setTrend(k)}>{label}</button>
          ))}
        </div>
        {against && <p className="warn caution">You're {side === "long" ? "buying" : "shorting"} against the trend you've noted. That's allowed, but it will be marked in your rule score.</p>}
      </div>

      <label className="form-row">
        <span className="field-label">Why are you taking this trade? (one sentence)</span>
        <textarea rows={2} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. Pulled back to the 20 average in an uptrend and closed back above it" />
      </label>

      <div className="form-row">
        <span className="field-label">How are you feeling? (optional)</span>
        <div className="chips">
          {MOODS.map(([k, label]) => (
            <button key={k} type="button" className={mood === k ? "chip on" : "chip"} onClick={() => setMood(mood === k ? "" : k)}>{label}</button>
          ))}
        </div>
      </div>

      {out && (
        <label className="check-row confirm">
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          I've checked it: {side === "long" ? "buy" : "short"} {atLevel ? "about " : ""}{out.units < 10 ? out.units.toFixed(4) : Math.floor(out.units).toLocaleString("en-GB")}{" "}
          {displayCode(symbol.code)}{atLevel ? " if it fills" : ""}, losing about {money(out.riskGbp)} if the stop-loss is hit.
        </label>
      )}

      <ul className="checklist">
        {checks.map((c) => <li key={c.text} className={c.ok ? "ok" : ""}><span aria-hidden="true">{c.ok ? "✓" : "○"}</span> {c.text}</li>)}
      </ul>

      {error && <p className="warn stop">{error}</p>}
      {error && when === "now" && /market's closed/i.test(error) && (
        <button type="button" className="ghost small" onClick={() => { setWhen("open"); setError(null); }}>
          Queue it for when the market opens instead
        </button>
      )}
      <div className="planner-actions">
        <button type="button" className="primary" disabled={!ready || busy} onClick={place}>
          {busy ? "Placing…" : atOpen ? `Place ${side === "long" ? "buy" : "sell"} for the open`
            : atLevel && priced ? `Place ${priced.kind.toLowerCase()} order` : `Place paper ${side === "long" ? "buy" : "short"}`}
        </button>
        <button type="button" className="ghost" onClick={() => setOpen(false)}>Cancel</button>
      </div>
      <p className="muted small-text">{atOpen ? "Paper only." : atLevel
        ? "It fills at your entry, or at the price it jumped to if it gaps past (plus the usual spread), sized on the balance at that moment. If a safeguard refuses it then, nothing is traded and you get an alert saying why. Paper only."
        : "It fills at the live price now (plus the usual spread), which may differ slightly from the entry line."}</p>
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

export function duration(seconds: number | null): string {
  if (seconds === null) return "–";
  const h = seconds / 3600;
  if (h < 1) return `${Math.max(1, Math.round(seconds / 60))} min`;
  if (h < 36) return `${h < 10 ? h.toFixed(1) : Math.round(h)} hours`;
  const d = h / 24;
  if (d < 14) return `${d < 10 ? d.toFixed(1) : Math.round(d)} days`;
  return `${(d / 7).toFixed(1)} weeks`;
}

/** How often, and how fast, the price has reached targets like this before the stop. History, not a forecast. */
function OddsBox({ symbol, timeframe, plan, mode, precision, onUseTarget, onAuthError }: {
  symbol: SymbolInfo; timeframe: string; plan: TradePlan; mode: string; precision: number;
  onUseTarget: (price: number) => void; onAuthError: (err: unknown) => void;
}) {
  const [odds, setOdds] = useState<TargetOdds | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      api
        .targetOdds({ symbol: symbol.code, timeframe, entry: plan.entry, stop: plan.stop, target: plan.target, mode })
        .then((o) => { setOdds(o); setError(null); })
        .catch((err) => {
          if (err instanceof ApiError && err.status === 401) onAuthError(err);
          setError(err instanceof Error ? err.message : "Couldn't work out the odds.");
        });
    }, 450);
    return () => window.clearTimeout(timer);
  }, [symbol.code, timeframe, plan.entry, plan.stop, plan.target, mode, onAuthError]);

  if (error) return <div className="odds"><h3>How realistic is this target?</h3><p className="muted small-text">{error}</p></div>;
  if (!odds) return <div className="odds"><h3>How realistic is this target?</h3><p className="muted small-text">Checking history…</p></div>;

  const c = odds.current;
  const r = (x: number) => `${x > 0 ? "+" : ""}${x.toFixed(2)}R`;
  const better = odds.best && (!c || odds.best.netR > c.netR + 0.005) ? odds.best : null;
  const isCurrent = (row: OddsRow) => c !== null && row.r === c.r;
  const rows = showAll ? odds.ladder : odds.ladder.filter((row) => [0.75, 1, 1.5, 2, 3].includes(row.r) || isCurrent(row) || row.r === odds.best.r);

  return (
    <div className="odds">
      <h3>How realistic is this target?</h3>
      {odds.sample && <p className="warn stop">Sample data: these odds mean nothing yet.</p>}
      {c ? (
        <>
          <p className="big">
            Reached before the stop in <b>{c.targetPct.toFixed(0)}%</b> of {odds.starts.toLocaleString("en-GB")} past cases,
            {c.medianSeconds !== null ? <> typically in <b>{duration(c.medianSeconds)}</b></> : null}.
          </p>
          <p className="muted small-text">
            {c.p25Seconds !== null && c.p75Seconds !== null && <>Half took between {duration(c.p25Seconds)} and {duration(c.p75Seconds)}. </>}
            Stop hit first {c.stopPct.toFixed(0)}%{c.neitherPct >= 1 ? `; neither within ${duration(odds.horizonSeconds)} ${c.neitherPct.toFixed(0)}%` : ""}.
          </p>
          <p className={`verdict ${c.viable ? "realistic" : "ambitious"}`}>
            {c.viable ? "Pays its way" : "Doesn't pay its way"}: averages <b>{r(c.netR)}</b> a trade after costs
            {c.neitherPct < 1
              ? <> (it needs to work {c.breakEvenPct.toFixed(0)}% of the time; it did {c.targetPct.toFixed(0)}%).</>
              : <> (target first {c.targetPct.toFixed(0)}%, stop first {c.stopPct.toFixed(0)}%, the rest went nowhere and count as break-even).</>}
          </p>
        </>
      ) : (
        <p className="muted small-text">Add a target to see its odds, or pick one from the table.</p>
      )}

      <table className="odds-table">
        <thead><tr><th>Target</th><th>Price</th><th className="num">Reached first</th><th className="num">Typical time</th><th className="num">After costs</th><th></th></tr></thead>
        <tbody>
          {rows.map((row: OddsRow) => (
            <tr key={row.r} className={`${isCurrent(row) ? "current" : ""} ${row.viable ? "viable" : ""}`}>
              <td>{row.r}R</td>
              <td className="mono">{row.targetPrice.toFixed(precision)}</td>
              <td className="num">{row.targetPct.toFixed(0)}%</td>
              <td className="num">{duration(row.medianSeconds)}</td>
              <td className={`num ${row.netR > 0 ? "up" : "down"}`}>{r(row.netR)}</td>
              <td>{!isCurrent(row) && <button type="button" className="link-button" onClick={() => onUseTarget(row.targetPrice)}>Use</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="planner-actions">
        {better && <button type="button" className="ghost small" onClick={() => onUseTarget(better.targetPrice)}>Use the best level here ({better.r}R, {r(better.netR)})</button>}
        <button type="button" className="link-button" onClick={() => setShowAll((s) => !s)}>{showAll ? "Fewer levels" : "All levels"}</button>
      </div>
      {!odds.anyViable && (
        <p className="note">No target paid its way for a random entry here after costs, so any edge has to come from the setup itself. Check the strategy's backtest before relying on it.</p>
      )}
      <p className="muted small-text">
        From every past {odds.timeframe} candle over {odds.years} years: entering at the close with your stop ({odds.stopAtr}× the typical candle range) and each target,
        which was touched first, and how long it took. This is how random entries fared. It's history, not a forecast.
      </p>
    </div>
  );
}
