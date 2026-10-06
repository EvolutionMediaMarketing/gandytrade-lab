import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { money } from "./BacktestPage";
import type { CalendarStatus, AlertStatus, BackupStatus, PaperAccount } from "./types";

interface Rule {
  key: "risk_pct" | "max_open_risk_pct" | "daily_loss_pct" | "max_drawdown_pct";
  field: keyof PaperAccount;
  label: string;
  min: number;
  max: number;
  step: number;
  help: (a: PaperAccount, v: number) => string;
}

const RULES: Rule[] = [
  {
    key: "risk_pct", field: "riskPct", label: "Risk per trade", min: 0.1, max: 2, step: 0.1,
    help: (a, v) => `Each trade is sized so that hitting its stop-loss loses about ${money(a.equity * v / 100)}.`,
  },
  {
    key: "max_open_risk_pct", field: "maxOpenRiskPct", label: "Most at risk at once", min: 1, max: 10, step: 0.5,
    help: (a, v) => `If every open trade hit its stop-loss together, you'd lose at most ${money(a.equity * v / 100)}. New trades are trimmed or refused to stay inside it.`,
  },
  {
    key: "daily_loss_pct", field: "dailyLossPct", label: "Daily loss limit", min: 0.5, max: 5, step: 0.5,
    help: (a, v) => `After losing ${money(a.equity * v / 100)} in a day, no new trades until tomorrow.`,
  },
  {
    key: "max_drawdown_pct", field: "maxDrawdownPct", label: "Pause after a fall of", min: 5, max: 25, step: 1,
    help: (_a, v) => `If the account falls ${v}% from its highest value, trading pauses until you've reviewed what happened.`,
  },
];

export default function SettingsPage({ onAuthError }: { onAuthError: (err: unknown) => void }) {
  const [accounts, setAccounts] = useState<PaperAccount[]>([]);
  const load = useCallback(() => {
    api.paperAccounts().then((r) => setAccounts(r.accounts)).catch(onAuthError);
  }, [onAuthError]);
  useEffect(load, [load]);

  return (
    <div className="page settings">
      <section>
        <h2>Settings</h2>
        <p className="muted">Risk safeguards for each paper account. They apply to every trade, by hand or automatic. Each has a safe range it can't go beyond.</p>
      </section>
      {accounts.filter((a) => !a.archived).map((a) => <AccountSettings key={a.id} account={a} onSaved={load} onAuthError={onAuthError} />)}
      <Alerts onAuthError={onAuthError} />
      <Backups onAuthError={onAuthError} />
      <CalendarDates onAuthError={onAuthError} />
      {accounts.some((a) => a.archived) && (
        <section className="card">
          <h3>Archived accounts</h3>
          <ul className="plain">
            {accounts.filter((a) => a.archived).map((a) => (
              <li key={a.id}>{a.name} · {money(a.equity)}{" "}
                <button type="button" className="link-button" onClick={() => api.changePaperAccount(a.id, { archived: false }).then(load).catch(onAuthError)}>Restore</button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function AccountSettings({ account, onSaved, onAuthError }: { account: PaperAccount; onSaved: () => void; onAuthError: (err: unknown) => void }) {
  const initial = () => Object.fromEntries(RULES.map((r) => [r.key, account[r.field] as number])) as Record<Rule["key"], number>;
  const [values, setValues] = useState(initial);
  const [name, setName] = useState(account.name);
  const [status, setStatus] = useState<string | null>(null);
  useEffect(() => {
    setValues(initial());
    setName(account.name);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account]);

  const changed = name !== account.name || RULES.some((r) => values[r.key] !== account[r.field]);
  const usedPct = account.openRiskLimit > 0 ? Math.min(100, (account.openRisk / account.openRiskLimit) * 100) : 0;

  function save() {
    setStatus(null);
    api
      .changePaperAccount(account.id, { name, ...values })
      .then(() => { setStatus("Saved."); onSaved(); })
      .catch((err) => { onAuthError(err); setStatus(err instanceof Error ? err.message : "Couldn't save."); });
  }

  return (
    <section className="card account-settings">
      <div className="settings-head">
        <input className="name-input" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} aria-label="Account name" />
        <span className="muted">{account.mode === "cash" ? "Real shares, no leverage" : "CFD / spread bet"} · {money(account.equity)}</span>
      </div>

      <div className="risk-meter" aria-label="Amount at risk now">
        <div className="risk-meter-bar"><i style={{ width: `${usedPct}%` }} className={usedPct >= 90 ? "full" : ""} /></div>
        <span className="muted small-text">At risk now: <b>{money(account.openRisk)}</b> of {money(account.openRiskLimit)} allowed</span>
      </div>

      <div className="rules">
        {RULES.map((r) => (
          <label key={r.key} className="rule">
            <span className="rule-head">
              <span>{r.label}</span>
              <span className="rule-value">{values[r.key]}%</span>
            </span>
            <input type="range" min={r.min} max={r.max} step={r.step} value={values[r.key]}
              onChange={(e) => setValues((v) => ({ ...v, [r.key]: Number(e.target.value) }))} />
            <span className="muted small-text">{r.help(account, values[r.key])}</span>
          </label>
        ))}
      </div>

      <div className="planner-actions">
        <button type="button" className="primary" disabled={!changed} onClick={save}>Save changes</button>
        {changed && <button type="button" className="ghost" onClick={() => { setValues(initial()); setName(account.name); }}>Undo</button>}
        {status && <span className="muted">{status}</span>}
        <span className="spacer" />
        <button type="button" className="ghost small" onClick={() => {
          if (window.confirm(`Archive “${account.name}”? It's hidden but kept, and can be restored here.`)) {
            api.changePaperAccount(account.id, { archived: true }).then(onSaved).catch(onAuthError);
          }
        }}>Archive account</button>
      </div>
    </section>
  );
}

const when = (iso: string) => new Date(iso).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function Backups({ onAuthError }: { onAuthError: (err: unknown) => void }) {
  const [status, setStatus] = useState<BackupStatus | null>(null);
  useEffect(() => { api.backupStatus().then(setStatus).catch(onAuthError); }, [onAuthError]);
  if (!status) return null;
  const last = status.runs[0];
  return (
    <section className="card backups">
      <h3>Backups</h3>
      <p className="muted small-text">
        Every night the database is copied, test-restored into a scratch database to prove it works{status.offServer ? ", then encrypted and copied to your Backblaze bucket" : ""}.
        The last 14 nightly copies are also kept on the server.
      </p>
      {!status.offServer && (
        <p className="warn caution">Off-server copies aren't set up yet, so a server failure would lose your data. See docs/BACKUPS.md.</p>
      )}
      {status.overdue && <p className="warn stop">No backup has worked for over two days. The latest problem is shown below.</p>}
      {!last ? <p className="muted">No backups have run yet. The first runs tonight, in the early hours (about 02:30 to 03:30 UK time).</p> : (
        <>
          <p>{status.lastOk ? <>Last good backup: <b>{when(status.lastOk)}</b></> : "No backup has worked yet."}</p>
          <div className="table-wrap">
            <table className="trades">
              <thead><tr><th>When</th><th>Result</th><th>Restore test</th><th>Off server</th><th>Details</th></tr></thead>
              <tbody>
                {status.runs.map((r, i) => (
                  <tr key={i}>
                    <td>{when(r.at)}</td>
                    <td className={r.ok ? "up" : "down"}>{r.ok ? "OK" : "Failed"}</td>
                    <td>{r.restoreTested ? "Passed" : "–"}</td>
                    <td>{r.uploaded ? `Yes (${(r.size / 1024).toFixed(0)} KB, encrypted)` : "No"}</td>
                    <td className="muted small-text">{r.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function Alerts({ onAuthError }: { onAuthError: (err: unknown) => void }) {
  const [status, setStatus] = useState<AlertStatus | null>(null);
  const [chats, setChats] = useState<{ chatId: string; name: string }[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.alertStatus().then(setStatus).catch(onAuthError); }, [onAuthError]);

  function run<T>(p: Promise<T>, done?: (v: T) => void) {
    setBusy(true);
    setNote(null);
    p.then((v) => done?.(v)).catch((err) => { onAuthError(err); setNote(err instanceof Error ? err.message : "That didn't work."); })
      .finally(() => setBusy(false));
  }
  if (!status) return null;

  return (
    <section className="card alerts-card">
      <h3>Alerts on your phone (Telegram)</h3>
      {!status.botConfigured ? (
        <>
          <p className="muted small-text">Get a message when an automatic trade opens or closes, a stop-loss or target is hit, or something pauses itself. Set-up takes about five minutes:</p>
          <ol className="steps">
            <li>In Telegram, open <b>@BotFather</b> (the official bot with a blue tick), send <code>/newbot</code>, and follow the prompts to name it (for example "GandyTrade alerts").</li>
            <li>BotFather replies with a <b>token</b>. Don't paste it into any chat. On the server, add it to the end of <code>/home/gandytradeco/gandytrade/app.env</code> as <code>GT_TELEGRAM_BOT_TOKEN=the token</code>.</li>
            <li>Run the usual update command, then come back here.</li>
          </ol>
        </>
      ) : !status.chatLinked ? (
        <>
          <p className="muted small-text">Your bot is ready. Now link the chat the alerts go to:</p>
          <ol className="steps">
            <li>In Telegram, open your new bot and send it any message (for example "hello").</li>
            <li><button type="button" className="small" disabled={busy} onClick={() => run(api.findChats(), (r) => setChats(r.chats))}>Find my chat</button></li>
          </ol>
          {chats && (chats.length === 0 ? <p className="warn caution small-text">No messages found yet. Send your bot a message, then try again.</p> : (
            <ul className="plain">
              {chats.map((c) => (
                <li key={c.chatId}>{c.name}{" "}
                  <button type="button" className="primary small" disabled={busy} onClick={() => run(api.linkChat(c.chatId), (s) => { setStatus(s); setChats(null); })}>Use this chat</button>
                </li>
              ))}
            </ul>
          ))}
        </>
      ) : (
        <>
          <p>Sending to <b>{status.chatName}</b>.{" "}
            <button type="button" className="link-button" disabled={busy} onClick={() => run(api.testAlert(), () => setNote("Test message sent: check Telegram."))}>Send a test</button>{" · "}
            <button type="button" className="link-button" disabled={busy} onClick={() => {
              if (window.confirm("Stop sending alerts to this chat?")) run(api.unlinkChat(), setStatus);
            }}>Unlink</button>
          </p>
          <div className="alert-kinds">
            {Object.entries(status.kindLabels).map(([key, label]) => (
              <label key={key} className="check-row">
                <input type="checkbox" checked={status.kinds.includes(key)} disabled={busy}
                  onChange={(e) => run(api.chooseAlerts(e.target.checked ? [...status.kinds, key] : status.kinds.filter((k) => k !== key)), setStatus)} />
                <span>{label}</span>
              </label>
            ))}
          </div>
          <p className="muted small-text">Trades you close yourself don't send alerts. Messages go out within about a minute.</p>
        </>
      )}
      {note && <p className="muted">{note}</p>}
      {status.recent.length > 0 && (
        <details>
          <summary className="muted small-text">Recent alerts</summary>
          <ul className="plain alert-history">
            {status.recent.map((a, i) => (
              <li key={i}>
                <span className="muted small-text">{when(a.at)} · {a.status === "sent" ? "sent" : a.status === "pending" ? "waiting" : a.status === "skipped" ? "not sent (switched off)" : `failed: ${a.error}`}</span>
                <pre>{a.text}</pre>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}


/** Economic calendar: how far ahead each official schedule goes, and a button to check the publishers for new dates. */
function CalendarDates({ onAuthError }: { onAuthError: (err: unknown) => void }) {
  const [status, setStatus] = useState<CalendarStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  useEffect(() => { api.calendarStatus().then(setStatus).catch(onAuthError); }, [onAuthError]);
  const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "–");
  return (
    <section className="card calendar-dates">
      <h3>Economic calendar dates</h3>
      <p className="muted small-text">
        Interest rate decisions, and inflation and jobs reports, from each publisher's own schedule. The app checks their pages
        for new dates every Saturday; press the button to check now. A page that can't be read keeps the dates already saved.
      </p>
      {status && (
        <div className="table-wrap">
          <table className="trades">
            <thead><tr><th>Schedule</th><th>Dates until</th><th>Last checked</th><th>Result</th></tr></thead>
            <tbody>
              {status.series.map((s) => (
                <tr key={s.key}>
                  <td><a href={s.source} target="_blank" rel="noopener noreferrer">{s.title}</a></td>
                  <td className={status.coverage.runningOut.includes(s.title) ? "down" : ""}>{s.until ? day(s.until) : "–"}</td>
                  <td className="muted">{day(s.checkedAt)}</td>
                  <td>
                    <span className={s.ok === false ? "down" : s.ok ? "up" : "muted"}>{s.message}</span>
                    {s.fromPages.length > 0 && (
                      <span className="muted small-text calendar-added">
                        <br />Added from the page: {s.fromPages.map((d) => day(`${d}T12:00:00Z`)).join(" · ")}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {error && <p className="warn stop">{error}</p>}
      <div className="planner-actions">
        <button type="button" className="primary small" disabled={busy} onClick={() => {
          setBusy(true);
          setError(null);
          api.calendarRefresh().then((s) => { setStatus(s); setChecked(true); })
            .catch((err) => { onAuthError(err); setError(err instanceof Error ? err.message : "The check didn't run."); })
            .finally(() => setBusy(false));
        }}>{busy ? "Checking the official sites… (up to a minute)" : "Check for new dates now"}</button>
        {checked && !busy && <span className="muted small-text">Done. Results above.</span>}
      </div>
      <p className="muted small-text">Some sites (the US Bureau of Labor Statistics especially) may refuse automated checks; if one keeps failing, ask Claude to add its dates by hand.</p>
    </section>
  );
}

