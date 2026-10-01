import { FormEvent, useState } from "react";
import { api } from "./api";

export default function Login({ onSignedIn }: { onSignedIn: (username: string) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!username || !password || code.length !== 6) {
      setError("Enter your username, password and the 6-digit code from your authenticator app.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const u = await api.login(username, password, code);
      onSignedIn(u.username);
    } catch (err: any) {
      setError(err.message ?? "Sign-in failed.");
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <form className="login-card" onSubmit={submit} noValidate>
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <div>
            <h1>GandyTrade Lab</h1>
            <p className="muted">Private. Paper first.</p>
          </div>
        </div>
        <label>
          Username
          <input autoComplete="username" value={username} onChange={(e) => { setUsername(e.target.value); setError(null); }} />
        </label>
        <label>
          Password
          <input type="password" autoComplete="current-password" value={password}
            onChange={(e) => { setPassword(e.target.value); setError(null); }} />
        </label>
        <label>
          Authenticator code
          <input inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="123456" value={code}
            onChange={(e) => { setCode(e.target.value.replace(/\D/g, "")); setError(null); }} />
        </label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button type="submit" className="primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </main>
  );
}
