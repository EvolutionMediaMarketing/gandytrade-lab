import { useEffect, useState } from "react";
import { api } from "./api";
import type { StrategyInfo } from "./types";

const GLOSSARY: [string, string][] = [
  ["Long / short", "Long means you profit if the price rises. Short means you profit if it falls (only possible with CFDs or spread bets)."],
  ["Stop-loss", "A price at which a losing trade closes automatically, so one bad trade can't do much damage. Every trade here has one."],
  ["Risk per trade", "How much of your account you'd lose if the stop-loss is hit. 1% of £200 is £2."],
  ["R", "Profit or loss measured in units of what you risked. Winning £4 on a £2 risk is +2R; a normal stop-loss is -1R."],
  ["ATR (Average True Range)", "How much a market typically moves in one candle. Used to set stop-losses that suit how jumpy the market is."],
  ["Spread", "The gap between the buy and sell price. It's how most brokers are paid, and you pay it on every trade."],
  ["Slippage", "Getting filled at a slightly worse price than you saw, especially in fast markets or when a stop is hit."],
  ["Drawdown", "How far the account has fallen from its highest point. A 20% drawdown on £200 means it fell to £160."],
  ["Leverage", "Trading a bigger position than your money. 30:1 means £100 controls £3,000. It magnifies losses just as much as gains."],
  ["CFD / spread bet", "Contracts that track a price without owning the asset. They allow leverage and shorting, charge overnight financing, and most retail accounts lose money with them."],
  ["Real shares", "Owning the actual shares. No leverage, so you can't lose more than you put in. UK shares carry 0.5% stamp duty when you buy."],
  ["Buy and hold", "Buy once and keep it. The yardstick: if a strategy can't beat this after costs, it isn't worth the effort."],
  ["Backtest", "Testing rules on past prices. Useful for ruling ideas out, but a good past result doesn't promise future profit."],
  ["Pence (GBX)", "London share prices are usually quoted in pence: 380 means £3.80 per share."],
];

export default function LearnPage({ onBacktest }: { onBacktest: (strategy: string) => void }) {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    api.strategies().then((r) => setStrategies(r.strategies)).catch(() => undefined);
  }, []);

  return (
    <div className="page learn">
      <section className="learn-intro">
        <h2>Strategies</h2>
        <p className="muted">Each strategy is a set of fixed rules. Read how it works, when it tends to work and fail, then test it yourself. Nothing here is a recommendation to trade.</p>
      </section>

      <div className="strategy-list">
        {strategies.map((s) => {
          const expanded = open === s.key;
          return (
            <article key={s.key} className={`card strategy ${expanded ? "open" : ""}`}>
              <button type="button" className="strategy-head" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : s.key)}>
                <span>
                  <h3>{s.name}</h3>
                  <span className="muted">{s.summary}</span>
                </span>
                <span className="caret" aria-hidden="true">{expanded ? "▾" : "▸"}</span>
              </button>
              {expanded && (
                <div className="strategy-body">
                  <h4>The rules</h4>
                  <ol>{s.rules.map((r, i) => <li key={i}>{r}</li>)}</ol>
                  <div className="two-col">
                    <div><h4>Tends to work when</h4><p>{s.worksWhen}</p></div>
                    <div><h4>Tends to fail when</h4><p>{s.failsWhen}</p></div>
                  </div>
                  {s.params.length > 0 && (
                    <>
                      <h4>Settings you can change</h4>
                      <ul className="plain">{s.params.map((p) => <li key={p.key}>{p.label}: default {p.default}{p.help ? `. ${p.help}` : ""}</li>)}</ul>
                    </>
                  )}
                  <h4>Try this</h4>
                  <p>{s.exercise}</p>
                  <button type="button" className="primary" onClick={() => onBacktest(s.key)}>Backtest this strategy</button>
                </div>
              )}
            </article>
          );
        })}
      </div>

      <section className="card glossary">
        <h2>Words you'll meet</h2>
        <dl>
          {GLOSSARY.map(([term, meaning]) => (
            <div key={term}><dt>{term}</dt><dd>{meaning}</dd></div>
          ))}
        </dl>
      </section>
    </div>
  );
}
