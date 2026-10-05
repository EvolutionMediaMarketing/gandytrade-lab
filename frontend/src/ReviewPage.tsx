import { useEffect, useState } from "react";
import { api } from "./api";
import { money } from "./BacktestPage";
import { displayCode } from "./MarketPicker";
import type { ReviewSummary, ReviewTrade, WeeklyReview } from "./types";

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${v.toFixed(0)}%`);
const r2 = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v.toFixed(2));
const LEVEL_CLASS: Record<string, string> = { stop: "warn stop", caution: "warn caution", info: "warn info", good: "warn good" };
const STUCK_LABEL: Record<string, string> = { yes: "Stuck to it", partly: "Partly", no: "Didn't" };

/** The weekly review: about 20 minutes looking back at the week, ending with one focus for next week. */
export default function ReviewPage({ onAuthError }: { onAuthError: (err: unknown) => void }) {
  const [review, setReview] = useState<WeeklyReview | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [focus, setFocus] = useState("");
  const [history, setHistory] = useState<ReviewSummary[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    api.currentReview().then((r) => { setReview(r); setAnswers(r.answers); setFocus(r.focus); }).catch(onAuthError);
    api.reviewHistory().then((h) => setHistory(h.reviews)).catch(onAuthError);
  };
  useEffect(load, [onAuthError]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (!review) return <div className="page review"><p className="muted">Loading…</p></div>;
  const f = review.facts;
  let stepNo = 0;
  const next = () => ++stepNo;  // steps are numbered in the order they appear
  const set = (key: string) => (e: { target: { value: string } }) => setAnswers((a) => ({ ...a, [key]: e.target.value }));

  function save(complete: boolean) {
    setBusy(true);
    setNote(null);
    api.saveReview(review!.week, { answers, focus, complete }).then((r) => {
      setReview(r);
      setNote(complete ? "Review saved. Your focus will be waiting at the top of next week's review." : "Draft saved.");
      api.reviewHistory().then((h) => setHistory(h.reviews)).catch(() => undefined);
    }).catch((err) => { onAuthError(err); setNote(err instanceof Error ? err.message : "Couldn't save."); })
      .finally(() => setBusy(false));
  }

  function copyForCoach() {
    api.reviewCoach(review!.week).then(async ({ text }) => {
      try {
        await navigator.clipboard.writeText(text);
        setNote("Copied. Paste it into a chat with Claude for a coaching review.");
      } catch {
        setNote(text);
      }
    }).catch(onAuthError);
  }

  return (
    <div className="page review">
      <header className="research-head">
        <h2>Weekly review <span className="muted">{f.label}</span></h2>
        <p className="muted">
          About 20 minutes. Look back at the week, be honest about what went well and what didn't, and finish with one thing to
          focus on next week. {review.completed ? "This week's review is done; you can still change your answers." : ""}
        </p>
      </header>

      <div className="stats">
        <Stat label="Trades closed" value={String(f.closed)} sub={`${f.manualClosed} yours · ${f.autoClosed} automatic · ${f.opened} opened`} />
        <Stat label="Result" value={money(f.net)} sub={`Costs ${money(f.costs)}`} tone={f.net} />
        <Stat label="Win rate · average R" value={`${pct(f.winRate)} · ${r2(f.avgR)}`} />
        <Stat label="Rule score (your trades)" value={f.ruleScore === null ? "–" : String(f.ruleScore)} sub="90+ is the goal" />
      </div>

      {f.closed === 0 && (
        <p className="warn info">No trades closed this week. That's fine: a quiet week is often a disciplined one. Answer what you can, and still set a focus.</p>
      )}

      {review.previousFocus && (
        <Step n={next()} title="Last week's focus">
          <p>You said: <b>"{review.previousFocus.focus}"</b></p>
          <div className="segmented wide">
            {(["yes", "partly", "no"] as const).map((k) => (
              <button key={k} type="button" className={answers.stuck === k ? "on" : ""} onClick={() => setAnswers((a) => ({ ...a, stuck: k }))}>
                {k === "yes" ? "I stuck to it" : k === "partly" ? "Partly" : "I didn't"}
              </button>
            ))}
          </div>
          <textarea rows={2} maxLength={1000} value={answers.stuckNote ?? ""} onChange={set("stuckNote")} placeholder="What helped, or what got in the way?" />
        </Step>
      )}

      <Step n={next()} title="Your best trade">
        {f.best ? <TradeBox t={f.best} /> : <p className="muted">No winning trades this week.</p>}
        <textarea rows={2} maxLength={1000} value={answers.best ?? ""} onChange={set("best")}
          placeholder={f.best ? "What did you (or the rules) do right that's worth repeating?" : "What went well this week, even without a win?"} />
      </Step>

      <Step n={next()} title="Your worst trade">
        {f.worst ? (
          <>
            <TradeBox t={f.worst} />
            <p className="muted small-text">A loss isn't a mistake if you followed the plan. Losses are part of any strategy that works.</p>
            <div className="segmented wide">
              {([["good_trade", "A good trade that lost"], ["mistake", "A mistake"], ["unsure", "Not sure"]] as const).map(([k, label]) => (
                <button key={k} type="button" className={answers.worstKind === k ? "on" : ""} onClick={() => setAnswers((a) => ({ ...a, worstKind: k }))}>{label}</button>
              ))}
            </div>
            <textarea rows={2} maxLength={1000} value={answers.worst ?? ""} onChange={set("worst")} placeholder="What happened? If it was a mistake, what would you do instead?" />
          </>
        ) : <p className="muted">No losing trades this week.</p>}
      </Step>

      <Step n={next()} title="Rules broken">
        {f.broken.length === 0 ? (
          <p className="warn good">No rules broken on your own trades this week.</p>
        ) : (
          <>
            <ul className="plain">
              {f.broken.map((t) => (
                <li key={t.id}>{t.side} {displayCode(t.symbol)} ({money(t.pnl)}): <span className="down">{t.flags.join("; ")}</span></li>
              ))}
            </ul>
            <textarea rows={2} maxLength={1000} value={answers.rules ?? ""} onChange={set("rules")} placeholder="What will you do differently next time?" />
          </>
        )}
        {f.noLesson > 0 && <p className="muted small-text">{f.noLesson} of your trades this week have no lesson in the journal yet.</p>}
      </Step>

      <Step n={next()} title="Automatic runs">
        {f.runs.length === 0 ? <p className="muted">No automatic runs going.</p> : (
          <div className="table-wrap">
            <table className="trades">
              <thead><tr><th>Run</th><th>Account</th><th className="num">This week</th><th className="num">All trades</th><th className="num">Avg R: paper vs backtest</th></tr></thead>
              <tbody>
                {f.runs.map((r, i) => (
                  <tr key={i} title={r.message}>
                    <td>{r.strategy} · {displayCode(r.symbol)} · {r.timeframe}{r.status === "paused" ? " (paused)" : ""}</td>
                    <td>{r.account}</td>
                    <td className="num">{r.weekTrades} ({money(r.weekNet)})</td>
                    <td className="num">{r.totalTrades}</td>
                    <td className="num">{r2(r.liveAvgR)} vs {r2(r.backtestAvgR)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted small-text">Leave runs alone unless something's broken: a few weeks of results say very little. Judge them after 30 or more trades.</p>
        <textarea rows={2} maxLength={1000} value={answers.runs ?? ""} onChange={set("runs")} placeholder="Anything you noticed about the automatic trading? (optional)" />
      </Step>

      {f.noticed.length > 0 && (
        <Step n={next()} title="What the app noticed">
          <ul className="warnings">
            {f.noticed.map((n, i) => <li key={i} className={LEVEL_CLASS[n.level] ?? "warn info"}><b>{n.title}</b> ({n.account}). {n.text}</li>)}
          </ul>
        </Step>
      )}

      <Step n={next()} title="Anything else">
        <textarea rows={2} maxLength={1000} value={answers.other ?? ""} onChange={set("other")} placeholder="Mood, news, something you read, a question for your coach… (optional)" />
      </Step>

      <Step n={next()} title="One focus for next week">
        <p className="muted small-text">Just one, specific and in your control. For example: "Write the lesson within an hour of closing", or "No new trade within 30 minutes of a loss".</p>
        <input className="focus-input" maxLength={200} value={focus} onChange={(e) => setFocus(e.target.value)} placeholder="Next week I will…" />
        <div className="planner-actions">
          <button type="button" className="primary" disabled={busy || focus.trim().length < 5} onClick={() => save(true)}>
            {review.completed ? "Save changes" : "Finish the review"}
          </button>
          <button type="button" className="ghost" disabled={busy} onClick={() => save(false)}>Save draft</button>
          {review.completed && <button type="button" className="ghost" onClick={copyForCoach}>Copy for a coaching chat</button>}
        </div>
        {note && (note.length > 200 ? <textarea className="export-text" readOnly rows={12} value={note} /> : <p className="muted">{note}</p>)}
      </Step>

      {history.length > 0 && (
        <div className="card">
          <h3>Past reviews</h3>
          <div className="table-wrap">
            <table className="trades">
              <thead><tr><th>Week</th><th>Focus</th><th>Following week</th><th className="num">Trades</th><th className="num">Result</th><th className="num">Rule score</th></tr></thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.week}>
                    <td>{h.label}</td><td>{h.focus}</td><td>{h.stuck ? STUCK_LABEL[h.stuck] : "–"}</td>
                    <td className="num">{h.closed ?? "–"}</td>
                    <td className={`num ${(h.net ?? 0) >= 0 ? "up" : "down"}`}>{h.net === null ? "–" : money(h.net)}</td>
                    <td className="num">{h.ruleScore ?? "–"}</td>
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

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="card review-step">
      <h3><span className="step-n">{n}</span>{title}</h3>
      {children}
    </section>
  );
}

function TradeBox({ t }: { t: ReviewTrade }) {
  return (
    <div className="trade-box">
      <b>{t.side === "buy" ? "Buy" : "Short"} {displayCode(t.symbol)}</b> · {t.who === "you" ? "your trade" : t.who} · {t.account}
      <span className={t.pnl >= 0 ? "up" : "down"}> {money(t.pnl)}{t.r !== null ? ` (${t.r.toFixed(2)}R)` : ""}</span>
      <div className="muted small-text">
        Closed {new Date(t.closed).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}: {t.exitReason}
        {t.reason ? ` · Why: ${t.reason}` : ""}{t.lesson ? ` · Your lesson: ${t.lesson}` : ""}
      </div>
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
