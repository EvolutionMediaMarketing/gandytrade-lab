import { useMemo, useState } from "react";
import type { MonteCarlo } from "./types";

const W = 760;
const H = 260;
const PAD = { l: 64, r: 16, t: 12, b: 28 };
const money = (v: number) => `£${v.toLocaleString("en-GB", { maximumFractionDigits: v < 1000 ? 2 : 0, minimumFractionDigits: v < 1000 ? 2 : 0 })}`;
const signed = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(0)}%`;

/** Monte Carlo check: the range of results and worst falls the same trades could have produced by luck. */
export default function MonteCarloCard({ mc }: { mc: MonteCarlo | null | undefined }) {
  if (!mc) return null;
  if (!mc.ok) {
    return (
      <div className="card">
        <h3>Monte Carlo check</h3>
        <p className="muted">{mc.reason}</p>
      </div>
    );
  }
  return (
    <div className="card monte-carlo">
      <h3>Monte Carlo check <span className="muted small-text">— what luck alone could have done with these trades</span></h3>
      <p className="muted small-text">
        {mc.simulations.toLocaleString("en-GB")} made-up histories, each drawing {mc.trades} trades at random from this backtest's
        real ones (some twice, some not at all) and replaying them from {money(mc.startBalance)} at {mc.riskPct}% risk a trade.
        Same strategy, same kind of trades, different luck.
      </p>
      <div className="stats">
        <Stat label="Typical worst fall" value={`${mc.worstFall["50"].toFixed(0)}%`} sub="half of histories fell less" />
        <Stat label="1-in-20 worst fall" value={`${mc.worstFall["95"].toFixed(0)}%`} sub={`1 in 100: ${mc.worstFall["99"].toFixed(0)}%`} tone="down" />
        <Stat label="Middle result" value={signed(mc.returnPct["50"])} sub={`9 in 10 between ${signed(mc.returnPct["5"])} and ${signed(mc.returnPct["95"])}`}
          tone={mc.returnPct["50"] >= 0 ? "up" : "down"} />
        <Stat label="Ended below the start" value={`${mc.chanceLoss.toFixed(0)}%`} sub={`Drawdown limit (${mc.drawdownLimitPct}%) reached in ${mc.chanceLimit.toFixed(0)}%`} />
      </div>
      <Fan mc={mc} />
      <ul className="warnings">
        {mc.summary.map((s, i) => <li key={i} className={`warn ${s.level}`}>{s.text}</li>)}
      </ul>
      <p className="muted small-text">
        Trades are replayed one after another, so in a basket, trades that overlapped are treated as if they came one at a time.
        Monte Carlo only reshuffles this backtest's trades: it can't foresee a kind of market the backtest never saw.
      </p>
    </div>
  );
}

function Fan({ mc }: { mc: Extract<MonteCarlo, { ok: true }> }) {
  const [hover, setHover] = useState<number | null>(null);
  const { step, bands, replay } = mc.curve;
  const geo = useMemo(() => {
    const all = [...bands["5"], ...bands["95"], ...replay, mc.startBalance];
    let lo = Math.min(...all);
    let hi = Math.max(...all);
    const pad = (hi - lo) * 0.06 || 1;
    lo = Math.max(0, lo - pad);
    hi += pad;
    const n = step.length;
    const x = (i: number) => PAD.l + (n <= 1 ? 0 : (i / (n - 1)) * (W - PAD.l - PAD.r));
    const y = (v: number) => PAD.t + (1 - (v - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
    const line = (vals: number[]) => vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
    const area = (top: number[], bottom: number[]) =>
      `${line(top)}${[...bottom].reverse().map((v, j) => `L${x(bottom.length - 1 - j).toFixed(1)},${y(v).toFixed(1)}`).join("")}Z`;
    const ticks = niceTicks(lo, hi, 4);
    return { x, y, line, area, ticks, n };
  }, [bands, replay, step, mc.startBalance]);

  const i = hover;
  return (
    <div className="fan-wrap">
      <div className="fan-legend small-text">
        <span><i className="sw band-outer" /> 9 in 10 histories</span>
        <span><i className="sw band-inner" /> middle half</span>
        <span><i className="sw line-mid" /> middle history</span>
        <span><i className="sw line-real" /> the backtest's own order</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="fan" role="img"
        aria-label={`Range of account balances over ${mc.trades} trades across ${mc.simulations} simulated histories`}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const box = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const px = ((e.clientX - box.left) / box.width) * W;
          const k = Math.round(((px - PAD.l) / (W - PAD.l - PAD.r)) * (geo.n - 1));
          setHover(Math.max(0, Math.min(geo.n - 1, k)));
        }}>
        {geo.ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={geo.y(t)} y2={geo.y(t)} className="fan-grid" />
            <text x={PAD.l - 8} y={geo.y(t) + 4} textAnchor="end" className="fan-axis">{money(t)}</text>
          </g>
        ))}
        <line x1={PAD.l} x2={W - PAD.r} y1={geo.y(mc.startBalance)} y2={geo.y(mc.startBalance)} className="fan-start" />
        <path d={geo.area(bands["95"], bands["5"])} className="band-outer" />
        <path d={geo.area(bands["75"], bands["25"])} className="band-inner" />
        <path d={geo.line(bands["50"])} className="line-mid" />
        <path d={geo.line(replay)} className="line-real" />
        <text x={PAD.l} y={H - 8} className="fan-axis">Trade 1</text>
        <text x={W - PAD.r} y={H - 8} textAnchor="end" className="fan-axis">Trade {step[step.length - 1]}</text>
        {i !== null && (
          <g pointerEvents="none">
            <line x1={geo.x(i)} x2={geo.x(i)} y1={PAD.t} y2={H - PAD.b} className="fan-cross" />
            <circle cx={geo.x(i)} cy={geo.y(bands["50"][i])} r={4} className="dot-mid" />
            <circle cx={geo.x(i)} cy={geo.y(replay[i])} r={4} className="dot-real" />
          </g>
        )}
      </svg>
      {i !== null && (
        <div className="fan-tip small-text" style={{
          left: `${(geo.x(i) / W) * 100}%`,
          transform: i > geo.n / 2 ? "translateX(calc(-100% - 10px))" : "translateX(10px)",  // beside the crosshair, not on it
        }}>
          <b>After trade {step[i]}</b>
          <span>Backtest's order: {money(replay[i])}</span>
          <span>Middle history: {money(bands["50"][i])}</span>
          <span>9 in 10: {money(bands["5"][i])} to {money(bands["95"][i])}</span>
        </div>
      )}
      <details className="small-text">
        <summary>Show as a table</summary>
        <table className="trades">
          <thead><tr><th></th><th className="num">1 in 20 (low)</th><th className="num">1 in 4</th><th className="num">Middle</th><th className="num">3 in 4</th><th className="num">1 in 20 (high)</th></tr></thead>
          <tbody>
            <tr><th>Final balance</th>{(["5", "25", "50", "75", "95"] as const).map((q) => <td key={q} className="num">{money(mc.final[q])}</td>)}</tr>
            <tr><th>Return</th>{(["5", "25", "50", "75", "95"] as const).map((q) => <td key={q} className="num">{signed(mc.returnPct[q])}</td>)}</tr>
          </tbody>
        </table>
        <p className="muted">Worst fall: half under {mc.worstFall["50"]}%, 3 in 4 under {mc.worstFall["75"]}%, 9 in 10 under {mc.worstFall["90"]}%,
          19 in 20 under {mc.worstFall["95"]}%, 99 in 100 under {mc.worstFall["99"]}%. Longest losing run: {mc.losingRun["50"]} typical,
          {" "}{mc.losingRun["95"]} in 1 in 20 histories, {mc.losingRun["99"]} in 1 in 100.</p>
      </details>
    </div>
  );
}

function niceTicks(lo: number, hi: number, count: number): number[] {
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(Math.round(v * 100) / 100);
  return out;
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "up" | "down" }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className={`stat-value ${tone ?? ""}`}>{value}</span>
      {sub && <span className="stat-sub muted">{sub}</span>}
    </div>
  );
}
