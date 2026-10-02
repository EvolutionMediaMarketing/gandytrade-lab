import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { money } from "./BacktestPage";
import type { BackupStatus, PaperAccount } from "./types";

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
      <Backups onAuthError={onAuthError} />
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
