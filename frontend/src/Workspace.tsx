import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import ChartView from "./ChartView";
import type { ActiveIndicator, Catalogue, ChartData, IndicatorDef } from "./types";

const STYLE_LABELS: Record<string, string> = {
  candles: "Candles",
  bars: "Bars (OHLC)",
  line: "Line",
  area: "Area",
  heikin_ashi: "Heikin Ashi",
};

const CLASS_LABELS: Record<string, string> = {
  forex: "Forex",
  metal: "Metals",
  commodity: "Commodities",
  stock: "US stocks",
  etf: "US ETFs",
};

interface Prefs {
  symbol: string;
  timeframe: string;
  style: string;
  indicators: ActiveIndicator[];
  autoRefresh: boolean;
}

// How often the chart refreshes itself, by timeframe (seconds).
const REFRESH_SECONDS: Record<string, number> = {
  "1m": 15, "5m": 30, "15m": 60, "30m": 60, "1h": 120, "4h": 300, "1d": 900, "1w": 1800, "1M": 3600,
};

const PREFS_KEY = "gt.workspace.v1";
const DEFAULT_PREFS: Prefs = {
  symbol: "EUR_USD",
  timeframe: "1d",
  style: "candles",
  indicators: [
    { id: "ema-1", type: "ema", params: { length: 50 } },
    { id: "volume-1", type: "volume", params: {} },
  ],
  autoRefresh: true,
};

function loadPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (raw) return { ...DEFAULT_PREFS, ...JSON.parse(raw) };
  } catch {
    /* storage unavailable */
  }
  return DEFAULT_PREFS;
}

function savePrefs(p: Prefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    /* storage unavailable */
  }
}

function defaults(def: IndicatorDef): Record<string, number> {
  return Object.fromEntries(def.params.map((p) => [p.key, p.default]));
}

export default function Workspace({ username, onSignedOut }: { username: string; onSignedOut: () => void }) {
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  const [data, setData] = useState<ChartData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const inFlight = useRef(false);

  const handleAuth = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) onSignedOut();
      else setError(err instanceof Error ? err.message : "Something went wrong.");
    },
    [onSignedOut],
  );

  useEffect(() => {
    api.catalogue().then(setCatalogue).catch(handleAuth);
  }, [handleAuth]);

  // `quiet` refreshes keep the current chart on screen and skip overlapping requests.
  const load = useCallback(
    (quiet = false) => {
      if (quiet && inFlight.current) return;
      inFlight.current = true;
      if (!quiet) setLoading(true);
      api
        .chart(prefs.symbol, prefs.timeframe, prefs.style, prefs.indicators)
        .then((d) => {
          setData(d);
          setError(null);
          setUpdatedAt(new Date());
        })
        .catch(handleAuth)
        .finally(() => {
          inFlight.current = false;
          setLoading(false);
        });
    },
    [prefs.symbol, prefs.timeframe, prefs.style, prefs.indicators, handleAuth],
  );

  useEffect(() => {
    savePrefs(prefs);
  }, [prefs]);

  useEffect(() => {
    load();
  }, [load]);

  // Automatic refresh, paused while the tab is hidden to save the free data allowance.
  useEffect(() => {
    if (!prefs.autoRefresh) return;
    const seconds = REFRESH_SECONDS[prefs.timeframe] ?? 60;
    const tick = () => {
      if (document.visibilityState === "visible") load(true);
    };
    const timer = window.setInterval(tick, seconds * 1000);
    document.addEventListener("visibilitychange", tick);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [prefs.autoRefresh, prefs.timeframe, load]);

  const grouped = useMemo(() => {
    const groups: Record<string, Catalogue["symbols"]> = {};
    for (const s of catalogue?.symbols ?? []) (groups[s.asset_class] ??= []).push(s);
    return groups;
  }, [catalogue]);

  const update = (patch: Partial<Prefs>) => setPrefs((p) => ({ ...p, ...patch }));

  function toggleIndicator(def: IndicatorDef) {
    const active = prefs.indicators.find((i) => i.type === def.type);
    if (active) update({ indicators: prefs.indicators.filter((i) => i !== active) });
    else update({ indicators: [...prefs.indicators, { id: `${def.type}-${Date.now()}`, type: def.type, params: defaults(def) }] });
  }

  function setParam(id: string, key: string, value: number) {
    update({
      indicators: prefs.indicators.map((i) => (i.id === id ? { ...i, params: { ...i.params, [key]: value } } : i)),
    });
  }

  async function signOut() {
    try {
      await api.logout();
    } finally {
      onSignedOut();
    }
  }

  const sourceLabel = data?.sample
    ? "Sample data"
    : data?.source === "oanda"
      ? "OANDA demo feed"
      : data?.source === "twelvedata"
        ? "Twelve Data"
        : "";

  return (
    <div className="workspace">
      <header className="topbar">
        <div className="brand small">
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-name">GandyTrade Lab</span>
        </div>
        <span className="mode-badge" title="No real money is involved anywhere in this version">Research · no real money</span>
        <div className="spacer" />
        <span className="muted user">{username}</span>
        <button className="ghost" onClick={signOut}>Sign out</button>
      </header>

      <div className="toolbar" role="toolbar" aria-label="Chart settings">
        <label className="field">
          <span>Market</span>
          <select value={prefs.symbol} onChange={(e) => update({ symbol: e.target.value })}>
            {Object.entries(grouped).map(([cls, syms]) => (
              <optgroup key={cls} label={CLASS_LABELS[cls] ?? cls}>
                {syms.map((s) => (
                  <option key={s.code} value={s.code}>
                    {s.code.replace("_", "/")} · {s.name}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>

        <div className="segmented" role="group" aria-label="Timeframe">
          {(catalogue?.timeframes ?? []).map((t) => (
            <button key={t.code} className={t.code === prefs.timeframe ? "on" : ""} title={t.label}
              onClick={() => update({ timeframe: t.code })}>
              {t.code}
            </button>
          ))}
        </div>

        <label className="field">
          <span>Style</span>
          <select value={prefs.style} onChange={(e) => update({ style: e.target.value })}>
            {(catalogue?.styles ?? Object.keys(STYLE_LABELS)).map((s) => (
              <option key={s} value={s}>{STYLE_LABELS[s] ?? s}</option>
            ))}
          </select>
        </label>

        <button className={panelOpen ? "secondary on" : "secondary"} onClick={() => setPanelOpen((o) => !o)}
          aria-expanded={panelOpen}>
          Indicators ({prefs.indicators.length})
        </button>
        <button className="ghost" onClick={() => load()} disabled={loading} title="Fetch the latest prices now">
          {loading ? "Loading…" : "Refresh"}
        </button>
        <label className="auto-refresh" title={`Updates every ${REFRESH_SECONDS[prefs.timeframe] ?? 60} seconds on this timeframe`}>
          <input type="checkbox" checked={prefs.autoRefresh} onChange={(e) => update({ autoRefresh: e.target.checked })} />
          Auto-refresh
        </label>
        {sourceLabel && <span className={data?.sample ? "source sample" : "source"}>{sourceLabel}</span>}
        {updatedAt && (
          <span className="updated muted">
            Updated {updatedAt.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </span>
        )}
      </div>

      {data?.warnings.map((w) => (
        <div key={w} className={data.sample ? "banner sample" : "banner"} role="status">{w}</div>
      ))}
      {data?.indicators.filter((i) => i.note).map((i) => (
        <div key={i.id} className="banner info" role="status">{i.note}</div>
      ))}
      {error && <div className="banner error" role="alert">{error}</div>}

      <div className={panelOpen ? "body with-panel" : "body"}>
        <section className="chart-area" aria-busy={loading}>
          {data && data.bars.length > 0 ? <ChartView data={data} /> : !error && <div className="splash">Loading chart…</div>}
        </section>

        {panelOpen && catalogue && (
          <aside className="panel" aria-label="Indicators">
            <h2>Indicators</h2>
            <p className="muted small-text">Tick to add. Each one explains what it measures.</p>
            {catalogue.indicators.map((def) => {
              const active = prefs.indicators.find((i) => i.type === def.type);
              return (
                <div key={def.type} className={active ? "ind on" : "ind"}>
                  <label className="ind-head">
                    <input type="checkbox" checked={!!active} onChange={() => toggleIndicator(def)} />
                    <span>{def.name}</span>
                    {def.intradayOnly && <em className="tag">intraday</em>}
                  </label>
                  <p className="ind-desc">{def.description}</p>
                  {active && def.params.length > 0 && (
                    <div className="params">
                      {def.params.map((p) => (
                        <label key={p.key}>
                          <span>{p.label}</span>
                          <input type="number" min={p.minimum} max={p.maximum} step={p.step}
                            defaultValue={active.params[p.key] ?? p.default}
                            onBlur={(e) => {
                              const v = Number(e.target.value);
                              if (Number.isFinite(v)) setParam(active.id, p.key, Math.min(p.maximum, Math.max(p.minimum, v)));
                            }} />
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </aside>
        )}
      </div>

      <footer className="footer">
        <span>Educational use only. Not financial advice.</span>
        <span>
          Charts by <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">TradingView</a> Lightweight Charts™
        </span>
      </footer>
    </div>
  );
}
