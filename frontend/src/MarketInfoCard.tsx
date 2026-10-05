import { useEffect, useState } from "react";
import { api } from "./api";
import type { MarketInfo } from "./types";

const bigMoney = (v: number, ccy = "USD") => {
  const sym = ccy === "USD" ? "$" : ccy === "GBP" ? "£" : ccy === "EUR" ? "€" : "";
  if (v >= 1e12) return `${sym}${(v / 1e12).toFixed(2)} trillion`;
  if (v >= 1e9) return `${sym}${(v / 1e9).toFixed(1)} billion`;
  if (v >= 1e6) return `${sym}${(v / 1e6).toFixed(0)} million`;
  return `${sym}${v.toLocaleString("en-GB")}`;
};
const ago = (secs: number) => {
  const m = Math.round((Date.now() / 1000 - secs) / 60);
  if (m < 60) return `${Math.max(1, m)} min ago`;
  if (m < 48 * 60) return `${Math.round(m / 60)} h ago`;
  return new Date(secs * 1000).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
};
const has = <K extends string>(o: unknown, k: K): o is Record<K, unknown> => !!o && typeof o === "object" && k in (o as object);

// Saved for this browser session, so moving the mouse back and forth doesn't re-ask the server.
const cache = new Map<string, MarketInfo>();

/** Background on a market: who the company is, its sector, a short summary and recent headlines;
 * or, for currencies, commodities, indices and bonds, what it is and what tends to move it.
 * Information only: nothing here places or changes a trade. */
export default function MarketInfoCard({ code, full, onAuthError }: { code: string; full: boolean; onAuthError?: (e: unknown) => void }) {
  const key = `${code}|${full}`;
  const [info, setInfo] = useState<MarketInfo | null>(cache.get(key) ?? cache.get(`${code}|true`) ?? null);
  const [loading, setLoading] = useState(!info);
  const [busy, setBusy] = useState<"" | "profile" | "news">("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const hit = cache.get(key) ?? cache.get(`${code}|true`);
    if (hit) { setInfo(hit); setLoading(false); return; }
    const ctl = new AbortController();
    setLoading(true);
    setError(null);
    api.marketInfo(code, full, ctl.signal)
      .then((r) => { cache.set(key, r); setInfo(r); })
      .catch((err) => { if (ctl.signal.aborted) return; onAuthError?.(err); setError("Couldn't load details just now."); })
      .finally(() => { if (!ctl.signal.aborted) setLoading(false); });
    return () => ctl.abort();
  }, [code, full, key, onAuthError]);

  function loadProfile() {
    setBusy("profile");
    api.marketInfo(code, true)
      .then((r) => { cache.set(`${code}|true`, r); cache.set(key, r); setInfo(r); })
      .catch((err) => { onAuthError?.(err); setError(err instanceof Error ? err.message : "Couldn't load details."); })
      .finally(() => setBusy(""));
  }
  function loadNews() {
    setBusy("news");
    api.marketNews(code)
      .then((r) => {
        setInfo((cur) => {
          if (!cur) return cur;
          const next = { ...cur, news: r.news, newsAt: r.newsAt, allowanceLeft: r.allowanceLeft };
          cache.set(`${code}|true`, next); cache.set(key, next);
          return next;
        });
      })
      .catch((err) => { onAuthError?.(err); setError(err instanceof Error ? err.message : "Couldn't load headlines."); })
      .finally(() => setBusy(""));
  }

  if (loading && !info) return <div className="info-card"><p className="muted small-text">Loading details…</p></div>;
  if (!info) return <div className="info-card"><p className="muted small-text">{error ?? "No details."}</p></div>;

  const p = info.profile && !has(info.profile, "none") && !has(info.profile, "error") ? info.profile : null;
  const wiki = info.wiki && has(info.wiki, "extract") ? (info.wiki as { title: string; extract: string; url: string; description: string }) : null;
  const summary = wiki?.extract || p?.description || "";  // Wikipedia's plain-English summary first
  const tags = [info.kind, p?.sector, p?.industry, p?.exchange || info.exchange, p?.country].filter(Boolean) as string[];
  const news = info.news && has(info.news, "items") ? (info.news as { items: { title: string; source: string; time: number; url: string }[] }).items : null;

  return (
    <div className="info-card" role="note" aria-label={`About ${info.name}`}>
      <div className="info-head">
        <b>{p?.name || info.name}</b>
        <span className="muted mono">{info.code.replace("_", "/")}</span>
      </div>
      <div className="info-tags">{[...new Set(tags)].map((t) => <span key={t} className="tag">{t}</span>)}</div>

      {info.note && <p className="info-text">{info.note.text}</p>}
      {info.note?.drivers.map((d) => <p key={d} className="info-text muted">{d}</p>)}
      {summary && <p className="info-text">{summary}</p>}

      {p && (
        <dl className="info-facts">
          {p.marketCap ? <><dt>Company value</dt><dd>{bigMoney(p.marketCap, p.currency)}</dd></> : null}
          {p.peRatio ? <><dt title="Share price ÷ yearly profit per share: how many years of today's profit the price pays for">Price ÷ earnings</dt><dd>{p.peRatio.toFixed(1)}</dd></> : null}
          {p.dividendYield ? <><dt title="Yearly dividends as a share of the price">Dividend</dt><dd>{(p.dividendYield * 100).toFixed(2)}% a year</dd></> : null}
          {p.low52 && p.high52 ? <><dt>Past year's range</dt><dd>{p.low52} – {p.high52}</dd></> : null}
        </dl>
      )}

      {info.canProfile && !p && (
        <p className="info-text small-text">
          {info.profile && has(info.profile, "error") ? <span className="muted">{String(info.profile.error)} </span> : null}
          {info.profile && has(info.profile, "none") ? <span className="muted">{String(info.profile.none)} </span> : (
            <button type="button" className="link-button" disabled={busy !== "" || info.allowanceLeft < 1} onClick={loadProfile}>
              {busy === "profile" ? "Loading…" : "Load sector and company details"}
            </button>
          )}
          <span className="muted"> ({info.allowanceLeft} lookups left today)</span>
        </p>
      )}

      {info.canNews && (
        <div className="info-news">
          <span className="field-label">Headlines {info.newsAt ? <span className="muted">· checked {ago(info.newsAt)}</span> : null}</span>
          {news?.length ? (
            <ul>
              {news.slice(0, 4).map((n) => (
                <li key={n.url}>
                  <a href={n.url} target="_blank" rel="noopener noreferrer nofollow">{n.title}</a>
                  <span className="muted"> · {n.source} · {ago(n.time)}</span>
                </li>
              ))}
            </ul>
          ) : info.news && has(info.news, "none") ? <p className="muted small-text">{String(info.news.none)}</p>
            : info.news && has(info.news, "error") ? <p className="muted small-text">{String(info.news.error)}</p>
            : (
              <button type="button" className="link-button small-text" disabled={busy !== "" || info.allowanceLeft < 1} onClick={loadNews}>
                {busy === "news" ? "Loading…" : `Load latest headlines (${info.allowanceLeft} lookups left today)`}
              </button>
            )}
          <p className="muted tiny">Headlines are information, not trade signals: by the time news reaches a free feed, prices have usually moved.</p>
        </div>
      )}

      {error && <p className="form-error small-text">{error}</p>}
      {wiki && (
        <p className="muted tiny">
          Summary from <a href={wiki.url} target="_blank" rel="noopener noreferrer">Wikipedia: {wiki.title}</a> (CC BY-SA)
          {p ? "; sector and figures from Alpha Vantage" : ""}.
        </p>
      )}
      {!wiki && p && <p className="muted tiny">Company details from Alpha Vantage.</p>}
    </div>
  );
}
