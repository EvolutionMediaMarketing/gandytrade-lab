/**
 * Market replay engine: fills your practice trades exactly as the backtester would.
 *
 *  1. At each new candle's open: an exit you asked for, then an entry you placed on the previous candle
 *     (sized from the balance at that moment: risk % of it, ÷ the stop distance in pounds; capped by leverage,
 *     or by cash for real shares; cancelled if the price opened beyond its stop-loss).
 *  2. During the candle: the stop-loss first, then the target (if one candle reached both, the stop is assumed
 *     to have come first). A price that opened beyond either fills at the open.
 *  3. At the close: the account is valued.
 *
 * Costs come from the server for this market and account type: half the spread plus slippage on every fill,
 * commission and currency fees, stamp duty on real-share purchases, and overnight financing on CFDs. Prices
 * are converted to pounds at each candle's own exchange rate.
 */

import type { BarData } from "./types";

export interface ReplayCosts {
  spread_pct: number;
  slippage_pct: number;
  commission_gbp: number;
  fx_fee_pct: number;
  stamp_duty_pct: number;
  financing_pct_year: number;
}

export interface ReplayMarket {
  bars: BarData[];
  rates: number[]; // price units per £1 at each candle
  startIndex: number;
  mode: "cash" | "cfd";
  costs: ReplayCosts;
  leverage: number;
}

export interface Pending { side: 1 | -1; stop: number; target: number | null }

export interface Position {
  side: 1 | -1;
  units: number;
  entryPrice: number; // fill, after spread and slippage
  entryMid: number;
  entryI: number;
  entryTime: number;
  stop: number;
  initialStop: number;
  target: number | null;
  riskGbp: number;
  entryFees: number;
  note: string;
}

export interface ClosedTrade {
  side: 1 | -1;
  entryTime: number;
  exitTime: number;
  entryPrice: number;
  exitPrice: number;
  stop: number;
  pnl: number;
  r: number | null;
  reason: string;
}

export interface ReplayState {
  i: number; // the last candle you can see
  startBalance: number;
  riskPct: number;
  cash: number;
  pos: Position | null;
  pending: Pending | null;
  exitAsked: boolean;
  trades: ClosedTrade[];
  equity: { time: number; value: number }[];
  messages: string[]; // what happened on the latest candle, in plain words
}

export function begin(m: ReplayMarket, startBalance: number, riskPct: number): ReplayState {
  const i = m.startIndex;
  return {
    i, startBalance, riskPct, cash: startBalance, pos: null, pending: null, exitAsked: false, trades: [],
    equity: [{ time: m.bars[i].time, value: startBalance }], messages: [],
  };
}

export const ended = (m: ReplayMarket, s: ReplayState) => s.i >= m.bars.length - 1;

function fill(m: ReplayMarket, mid: number, buying: boolean): number {
  const adj = m.costs.spread_pct / 200 + m.costs.slippage_pct / 100;
  return buying ? mid * (1 + adj) : mid * (1 - adj);
}

function fees(m: ReplayMarket, units: number, price: number, i: number, buying: boolean, opening: boolean): number {
  const value = (units * price) / m.rates[i];
  let f = m.costs.commission_gbp + (value * m.costs.fx_fee_pct) / 100;
  if (buying && opening && m.mode === "cash") f += (value * m.costs.stamp_duty_pct) / 100;
  return f;
}

function financing(m: ReplayMarket, p: Position, i: number): number {
  if (m.mode !== "cfd" || !m.costs.financing_pct_year) return 0;
  const nights = Math.max(0, Math.floor(m.bars[i].time / 86400) - Math.floor(p.entryTime / 86400));
  const value = (p.units * p.entryMid) / m.rates[p.entryI];
  return (value * m.costs.financing_pct_year) / 100 / 365 * nights;
}

/** Profit or loss on the open position at a candle's close, after financing so far (not exit costs). */
export function openPnl(m: ReplayMarket, s: ReplayState, i = s.i): number {
  const p = s.pos;
  if (!p) return 0;
  return ((m.bars[i].close - p.entryPrice) * p.side * p.units) / m.rates[i] - financing(m, p, i);
}

export const equityNow = (m: ReplayMarket, s: ReplayState) => s.cash + openPnl(m, s);

function close(m: ReplayMarket, s: ReplayState, i: number, level: number, reason: string): void {
  const p = s.pos!;
  const price = fill(m, level, p.side < 0);
  const exitFees = fees(m, p.units, price, i, p.side < 0, false) + financing(m, p, i);
  const move = ((price - p.entryPrice) * p.side * p.units) / m.rates[i];
  s.cash += move - exitFees;
  const pnl = move - exitFees - p.entryFees;
  s.trades.push({
    side: p.side, entryTime: p.entryTime, exitTime: m.bars[i].time, entryPrice: p.entryPrice, exitPrice: price,
    stop: p.initialStop, pnl, r: p.riskGbp > 0 ? pnl / p.riskGbp : null, reason,
  });
  s.messages.push(`${reason}: ${p.side > 0 ? "buy" : "short"} closed at ${price.toPrecision(6)}, ${pnl >= 0 ? "+" : "−"}£${Math.abs(pnl).toFixed(2)}.`);
  s.pos = null;
}

/** Reveal the next candle and fill whatever is due. Returns a new state (the old one is left as it was). */
export function step(m: ReplayMarket, prev: ReplayState): ReplayState {
  if (ended(m, prev)) return prev;
  const s: ReplayState = { ...prev, trades: [...prev.trades], equity: [...prev.equity], messages: [],
    pos: prev.pos ? { ...prev.pos } : null };
  const j = s.i + 1;
  const b = m.bars[j];
  const rate = m.rates[j];

  // 1. At the open: an exit you asked for, then an entry placed on the last candle.
  if (s.exitAsked && s.pos) close(m, s, j, b.open, "Closed by you");
  s.exitAsked = false;
  if (s.pending && !s.pos) {
    const { side, stop } = s.pending;
    let { target } = s.pending;
    s.pending = null;
    const price = fill(m, b.open, side > 0);
    if ((b.open - stop) * side <= 0) {
      s.messages.push("Your order was cancelled: the price opened beyond its stop-loss.");
    } else {
      const lossPerUnit = Math.abs(price - stop) / rate;
      let units = (s.cash * s.riskPct) / 100 / lossPerUnit;
      const unitValue = price / rate;
      const feeRate = (m.costs.fx_fee_pct + (m.mode === "cash" && side > 0 ? m.costs.stamp_duty_pct : 0)) / 100;
      const most = m.mode === "cash" ? s.cash / (unitValue * (1 + feeRate)) : (s.cash * m.leverage) / unitValue;
      let note = "";
      if (units > most) {
        units = most;
        note = m.mode === "cash" ? "Smaller than planned: not enough cash for the full size." : "Smaller than planned: leverage cap.";
      }
      if (units * unitValue < 0.01) {
        s.messages.push("Your order was cancelled: not enough money left in the account.");
      } else {
        const entryFees = fees(m, units, price, j, side > 0, true);
        s.cash -= entryFees;
        if (target !== null && (target - b.open) * side <= 0) target = null;
        s.pos = {
          side, units, entryPrice: price, entryMid: b.open, entryI: j, entryTime: b.time, stop, initialStop: stop, target,
          riskGbp: units * lossPerUnit, entryFees, note,
        };
        s.messages.push(`${side > 0 ? "Bought" : "Shorted"} at ${price.toPrecision(6)}, risking £${(units * lossPerUnit).toFixed(2)}.${note ? " " + note : ""}`);
      }
    }
  }

  // 2. During the candle: stop-loss first, then the target.
  const p = s.pos;
  if (p) {
    const hitStop = p.side > 0 ? b.low <= p.stop : b.high >= p.stop;
    if (hitStop) {
      const gapped = (b.open - p.stop) * p.side <= 0 && p.entryI < j;
      close(m, s, j, gapped ? b.open : p.stop, gapped ? "Stop-loss (gapped through)" : "Stop-loss");
    } else if (p.target !== null && (p.side > 0 ? b.high >= p.target : b.low <= p.target)) {
      const gapped = (b.open - p.target) * p.side >= 0 && p.entryI < j;
      close(m, s, j, gapped ? b.open : p.target, "Target reached");
    }
  }

  // 3. At the close: value the account.
  s.i = j;
  s.equity.push({ time: b.time, value: equityNow(m, s) });
  return s;
}

/** Place an order to fill at the next candle's open. Returns an error message, or the new state. */
export function queueEntry(m: ReplayMarket, s: ReplayState, side: 1 | -1, stop: number, target: number | null): ReplayState | string {
  if (s.pos || s.pending) return "One trade at a time: close or cancel the current one first.";
  if (ended(m, s)) return "The replay has ended.";
  if (m.mode === "cash" && side < 0) return "With real shares you can only buy.";
  const last = m.bars[s.i].close;
  if (!(stop > 0) || (last - stop) * side <= 0) return `The stop-loss must be ${side > 0 ? "below" : "above"} the price (${last.toPrecision(6)}).`;
  if (target !== null && (target - last) * side <= 0) return "The target is on the wrong side of the price.";
  return { ...s, pending: { side, stop, target }, messages: [] };
}

export function moveStop(s: ReplayState, stop: number, price: number): ReplayState | string {
  if (!s.pos) return "No open trade.";
  if ((price - stop) * s.pos.side <= 0) return "That's past the current price: it would close the trade straight away. Close it instead.";
  return { ...s, pos: { ...s.pos, stop } };
}

/** Typical candle range (ATR 14) of the candles you can see, for a sensible default stop. */
export function atr(bars: BarData[], upTo: number, length = 14): number {
  const from = Math.max(1, upTo - length + 1);
  let sum = 0;
  let n = 0;
  for (let k = from; k <= upTo; k++) {
    const b = bars[k];
    const pc = bars[k - 1].close;
    sum += Math.max(b.high - b.low, Math.abs(b.high - pc), Math.abs(b.low - pc));
    n++;
  }
  return n ? sum / n : 0;
}

export interface Score {
  candles: number;
  trades: number;
  wins: number;
  net: number;
  returnPct: number;
  buyHoldPct: number;
  maxDrawdownPct: number;
  avgR: number | null;
  biggestWin: number | null;
  biggestLoss: number | null;
}

export function score(m: ReplayMarket, s: ReplayState): Score {
  const final = equityNow(m, s);
  let peak = s.startBalance;
  let worst = 0;
  for (const e of s.equity) {
    peak = Math.max(peak, e.value);
    if (peak > 0) worst = Math.max(worst, ((peak - e.value) / peak) * 100);
  }
  const first = m.bars[m.startIndex];
  const last = m.bars[s.i];
  const adj = m.costs.spread_pct / 200 + m.costs.slippage_pct / 100;
  const hold = ((last.close * (1 - adj)) / m.rates[s.i]) / ((first.close * (1 + adj)) / m.rates[m.startIndex]);
  const rs = s.trades.map((t) => t.r).filter((r): r is number => r !== null);
  const pnls = s.trades.map((t) => t.pnl);
  return {
    candles: s.i - m.startIndex,
    trades: s.trades.length,
    wins: s.trades.filter((t) => t.pnl > 0).length,
    net: final - s.startBalance,
    returnPct: ((final - s.startBalance) / s.startBalance) * 100,
    buyHoldPct: (hold - 1) * 100,
    maxDrawdownPct: worst,
    avgR: rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : null,
    biggestWin: pnls.length ? Math.max(...pnls) : null,
    biggestLoss: pnls.length ? Math.min(...pnls) : null,
  };
}
