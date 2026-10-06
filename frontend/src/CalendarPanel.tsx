import { useEffect, useState } from "react";
import { api } from "./api";
import type { CalendarEvent, CalendarResponse } from "./types";

const UK = "Europe/London";

export function inWords(seconds: number): string {
  const s = Math.abs(seconds);
  const h = s / 3600;
  const text = h < 1 ? `${Math.max(1, Math.round(s / 60))} min` : h < 48 ? `${Math.round(h)} hours` : `${Math.round(h / 24)} days`;
  return seconds >= 0 ? `in ${text}` : `${text} ago`;
}

export function ukTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: UK });
}

/** The coming high-impact events, for the market on the chart: rate decisions, inflation and jobs reports. */
export default function CalendarPanel({ symbol, onAuthError }: { symbol: string; onAuthError: (err: unknown) => void }) {
  const [data, setData] = useState<CalendarResponse | null>(null);
  const [onlyThis, setOnlyThis] = useState(true);
  useEffect(() => {
    setData(null);
    api.calendar({ symbol, days: 21 }).then(setData).catch(onAuthError);
  }, [symbol, onAuthError]);

  if (!data) return <p className="muted">Loading the calendar…</p>;
  const shown = data.events.filter((e) => e.inSeconds > -6 * 3600 && (!onlyThis || e.affects));
  const days = new Map<string, CalendarEvent[]>();
  for (const e of shown) {
    const day = new Date(e.time * 1000).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", timeZone: UK });
    days.set(day, [...(days.get(day) ?? []), e]);
  }
  return (
    <div className="calendar-panel">
      <h2>Economic calendar</h2>
      <p className="muted small-text">
        The next three weeks' high-impact events: interest rate decisions, and inflation and jobs reports. Prices can jump
        and spreads widen around them, and stop-losses can be filled worse than set. Information only, never a trade signal.
      </p>
      <label className="check-row"><input type="checkbox" checked={onlyThis} onChange={(e) => setOnlyThis(e.target.checked)} /> Only events that move this market</label>
      {data.coverage.runningOut.length > 0 && (
        <p className="warn caution">The schedule for {data.coverage.runningOut.join(", ")} runs out within a month. The app checks for new dates
          every Saturday, or use <a href="#/settings">Settings → Economic calendar dates</a> to check now.</p>
      )}
      {shown.length === 0 ? <p className="muted">Nothing scheduled {onlyThis ? "for this market " : ""}in the next three weeks.</p> : (
        [...days.entries()].map(([day, list]) => (
          <section key={day} className="calendar-day">
            <h3>{day}</h3>
            <ul>
              {list.map((e) => (
                <li key={`${e.key}-${e.time}`} className={e.affects ? "affects" : ""}>
                  <span className="calendar-time">
                    {new Date(e.time * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: UK })}{e.approx ? "≈" : ""}
                  </span>
                  <span>
                    <b>{e.title}</b>{e.tentative && <span className="muted"> (date tentative)</span>}
                    <span className="muted small-text"> {inWords(e.inSeconds)}</span>
                    <span className="calendar-what">{e.what}</span>
                    <a href={e.source} target="_blank" rel="noopener noreferrer" className="small-text">Official schedule</a>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
      <p className="muted small-text">UK times. ≈ means no fixed time. From the publishers' own schedules, checked {data.coverage.checked}.</p>
    </div>
  );
}
