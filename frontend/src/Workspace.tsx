import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Time } from "lightweight-charts";
import { api, ApiError } from "./api";
import ChartView from "./ChartView";
import BacktestPage, { type BacktestInit } from "./BacktestPage";
import LearnPage from "./LearnPage";
import JournalPage from "./JournalPage";
import CalendarPanel, { inWords } from "./CalendarPanel";
import ReplayPage from "./ReplayPage";
import BuilderPage from "./BuilderPage";
import MarketPicker, { displayCode } from "./MarketPicker";
import PaperPage from "./PaperPage";
import DashboardPage from "./DashboardPage";
import BasketPanel from "./BasketPanel";
import ReviewPage from "./ReviewPage";
import ResearchPage from "./ResearchPage";
import type { ChartMarker, ChartNote, ShownTrade } from "./ChartView";
import type { TradePlan } from "./PlanZones";
import SettingsPage from "./SettingsPage";
import SignalPanel from "./SignalPanel";
import TradePlanner from "./TradePlanner";
import { useLivePrices } from "./useLivePrices";
import ToolsPage from "./ToolsPage";
import type { ActiveIndicator, Catalogue, ChartData, IndicatorDef, SymbolInfo, AutoPrefill, BasketInit, PriceOrder, PaperTrade, CalendarResponse } from "./types";

const STYLE_LABELS: Record<string, string> = {
  candles: "Candles",
  bars: "Bars (OHLC)",
  line: "Line",
  area: "Area",
  heikin_ashi: "Heikin Ashi",
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

const PAGES = [
  { key: "charts", label: "Charts" },
  { key: "replay", label: "Replay" },
  { key: "backtest", label: "Backtest" },
  { key: "builder", label: "Builder" },
  { key: "research", label: "Research" },
  { key: "paper", label: "Paper" },
  { key: "journal", label: "Journal" },
  { key: "dashboard", label: "Dashboard" },
  { key: "review", label: "Review" },
  { key: "tools", label: "Tools" },
  { key: "learn", label: "Learn" },
  { key: "settings", label: "Settings" },
] as const;
type Page = (typeof PAGES)[number]["key"];

function pageFromHash(): Page {
  const h = window.location.hash.replace(/^#\/?/, "");
  return (PAGES.find((p) => p.key === h)?.key ?? "charts") as Page;
}

export default function Workspace({ username, onSignedOut }: { username: string; onSignedOut: () => void }) {
  const [page, setPage] = useState<Page>(pageFromHash);
  const [backupOverdue, setBackupOverdue] = useState(false);
  // An open paper trade picked on the Paper page, shown on the chart until you hide it.
  const [shownTrade, setShownTrade] = useState<ShownTrade | null>(null);
  useEffect(() => {
    api.backupStatus(true).then((b) => setBackupOverdue(b.overdue)).catch(() => {});
  }, [page]);
  const [basketMode, setBasketMode] = useState(false);
  const [basketInit, setBasketInit] = useState<BasketInit | null>(null);
  const [autoPrefill, setAutoPrefill] = useState<AutoPrefill | null>(null);
  const [paperOpen, setPaperOpen] = useState<number | null>(null);
  const [backtestInit, setBacktestInit] = useState<BacktestInit | undefined>();

  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = (p: Page) => {
    window.location.hash = `/${p}`;
    setPage(p);
    window.scrollTo({ top: 0 });
  };

  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [favourites, setFavourites] = useState<SymbolInfo[]>([]);
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  const [data, setData] = useState<ChartData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [panel, setPanel] = useState<"" | "indicators" | "signals" | "plan" | "calendar">("");
  const [plan, setPlan] = useState<TradePlan | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const inFlight = useRef(false);
  // When you last touched the page, and when we last asked the server for data. An automatic
  // refresh only counts as activity if you've used the mouse, keyboard or screen since then.
  const lastInput = useRef(Date.now());
  const lastRequest = useRef(0);

  useEffect(() => {
    const mark = () => {
      lastInput.current = Date.now();
    };
    const events = ["pointerdown", "pointermove", "keydown", "wheel", "touchstart"] as const;
    events.forEach((e) => window.addEventListener(e, mark, { passive: true }));
    return () => events.forEach((e) => window.removeEventListener(e, mark));
  }, []);

  const handleAuth = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) onSignedOut();
      else setError(err instanceof Error ? err.message : "Something went wrong.");
    },
    [onSignedOut],
  );

  useEffect(() => {
    api.catalogue().then(setCatalogue).catch(handleAuth);
    api.favourites().then((r) => setFavourites(r.favourites)).catch(handleAuth);
  }, [handleAuth]);

  // Star or unstar a market. The list updates at once and is then confirmed by the server.
  const toggleFavourite = useCallback(
    (symbol: SymbolInfo, on: boolean) => {
      setFavourites((list) => (on ? [...list.filter((f) => f.code !== symbol.code), symbol] : list.filter((f) => f.code !== symbol.code)));
      api
        .setFavourite(symbol.code, on)
        .then((r) => setFavourites(r.favourites))
        .catch((err) => {
          handleAuth(err);
          api.favourites().then((r) => setFavourites(r.favourites)).catch(() => undefined);
        });
    },
    [handleAuth],
  );

  // `quiet` refreshes keep the current chart on screen and skip overlapping requests.
  const load = useCallback(
    (quiet = false) => {
      if (quiet && inFlight.current) return;
      inFlight.current = true;
      if (!quiet) setLoading(true);
      const background = quiet && lastInput.current <= lastRequest.current;
      lastRequest.current = Date.now();
      api
        .chart(prefs.symbol, prefs.timeframe, prefs.style, prefs.indicators, background)
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
    if (page === "charts") load();
  }, [load, page]);

  // Automatic refresh, paused while the tab is hidden to save the free data allowance.
  useEffect(() => {
    if (!prefs.autoRefresh || page !== "charts") return;
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
  }, [prefs.autoRefresh, prefs.timeframe, load, page]);

  const update = (patch: Partial<Prefs>) => setPrefs((p) => ({ ...p, ...patch }));

  // Live prices for OANDA markets (currencies, metals, commodities, indices) while the chart is on screen.
  const streamable = page === "charts" && !!data && data.source === "oanda" && data.symbol.code === prefs.symbol;
  const { prices: livePrices, live } = useLivePrices(streamable ? [prefs.symbol] : [], streamable);
  const livePrice = streamable ? livePrices[prefs.symbol] ?? null : null;

  // A fresh plan: entry at the latest price, stop 2 × the daily ATR away on the right side, target at twice the risk (2R).
  const lastClose = data && data.symbol.code === prefs.symbol && data.bars.length ? data.bars[data.bars.length - 1].close : null;
  const lastCloseRef = useRef<number | null>(lastClose);
  lastCloseRef.current = lastClose;
  const startPlan = useCallback((side: "long" | "short" = "long") => {
    api
      .quote(prefs.symbol)
      .then((q) => {
        const entry = lastCloseRef.current ?? q.price; // the price you can see on the chart
        const distance = Math.min(q.dailyAtr ? 2 * q.dailyAtr : entry * 0.02, entry * 0.3);
        const sign = side === "long" ? 1 : -1;
        const round = (v: number) => Number(v.toFixed(q.symbol.precision));
        const target = entry + sign * 2 * distance;
        setPlan({ entry: round(entry), stop: round(entry - sign * distance), target: target > 0 ? round(target) : null });
      })
      .catch(handleAuth);
  }, [prefs.symbol, handleAuth]);

  // With "stop and target move with the entry" on (the default), dragging or typing the entry carries the
  // stop-loss and target along at the same distances, so the risk stays as planned.
  const [linked, setLinked] = useState(true);
  const linkedRef = useRef(linked);
  linkedRef.current = linked;
  const precisionRef = useRef(5);
  precisionRef.current = data?.symbol.precision ?? 5;
  const changePlan = useCallback((next: TradePlan | null) => {
    setPlan((prev) => {
      if (!next || !prev || !linkedRef.current) return next;
      if (next.entry === prev.entry || next.stop !== prev.stop || next.target !== prev.target) return next;
      const shift = next.entry - prev.entry;
      const round = (v: number) => Number(v.toFixed(precisionRef.current));
      const stop = round(prev.stop + shift);
      const target = prev.target === null ? null : round(prev.target + shift);
      return { ...next, stop: stop > 0 ? stop : prev.stop, target: target !== null && target > 0 ? target : prev.target };
    });
  }, []);

  // A new market means a new plan.
  useEffect(() => {
    setPlan(null);
  }, [prefs.symbol]);

  // Economic calendar: past events affecting this market marked on the chart (hover for what it was), and a dot
  // on the Calendar button plus a banner when one is due within 24 hours.
  const [calendarEvents, setCalendarEvents] = useState<CalendarResponse | null>(null);
  useEffect(() => {
    if (page !== "charts") return;
    api.calendar({ symbol: prefs.symbol, days: 2, past_days: 365 }).then(setCalendarEvents).catch(() => setCalendarEvents(null));
  }, [page, prefs.symbol]);
  const calendarSoon = calendarEvents?.soon ?? null;
  const calendarMarks = useMemo(() => {
    const bars = data && data.symbol.code === prefs.symbol ? data.bars : [];
    const markers: ChartMarker[] = [];
    const notes: ChartNote[] = [];
    if (!bars.length || !calendarEvents) return { markers, notes };
    for (const e of calendarEvents.events) {
      if (!e.affects || e.inSeconds > 0 || e.time < bars[0].time) continue;
      let at = -1;
      for (let k = bars.length - 1; k >= 0; k--) { if (bars[k].time <= e.time) { at = k; break; } }
      if (at < 0) continue;
      const t = bars[at].time;
      markers.push({ time: t as Time, position: "belowBar", shape: "square", color: "#c084fc", text: "" });
      notes.push({ time: t, kind: "news", title: e.title,
        text: `${new Date(e.time * 1000).toLocaleString("en-GB", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" })} UK. ${e.what}` });
    }
    markers.sort((a, b) => (a.time as number) - (b.time as number));
    return { markers, notes };
  }, [calendarEvents, data, prefs.symbol]);

  // Paper price orders waiting on this market, drawn on the chart; refreshed every minute (the worker's pace).
  const [priceOrders, setPriceOrders] = useState<PriceOrder[]>([]);
  const loadOrders = useCallback(() => {
    api.priceOrders({ symbol: prefs.symbol }).then((r) => setPriceOrders(r.waiting)).catch(() => setPriceOrders([]));
  }, [prefs.symbol]);
  useEffect(() => {
    if (page !== "charts") return;
    loadOrders();
    const timer = window.setInterval(loadOrders, 60_000);
    return () => window.clearInterval(timer);
  }, [page, loadOrders]);

  useEffect(() => {
    if (panel === "plan" && plan === null) startPlan("long");
  }, [panel, plan, startPlan]);

  // Open the Charts page on a paper trade, with its lines and marks (from the Paper and Journal pages).
  function showTrade(t: PaperTrade, opts?: { others?: PaperTrade[]; all?: boolean; label?: string }) {
    const secs = (iso: string | null) => (iso ? Math.floor(Date.parse(iso) / 1000) : null);
    const others = (opts?.others ?? []).map((o) => ({ id: o.id, side: o.side, entryTime: secs(o.entryTime)!,
      exitTime: o.status === "closed" ? secs(o.exitTime) : null, pnl: o.status === "closed" ? o.pnl : o.unrealised ?? null }));
    setShownTrade({ id: opts?.all ? -t.id : t.id, symbol: t.symbol, side: t.side, entryPrice: t.entryPrice,
      entryTime: secs(t.entryTime)!, stop: t.stop, target: t.target,
      exitPrice: t.status === "closed" ? t.exitPrice : null,
      exitTime: t.status === "closed" ? secs(t.exitTime) : null,
      pnl: t.pnl, exitReason: t.exitReason, others, allOnly: !!opts?.all, label: opts?.label });
    const tfKnown = (catalogue?.timeframes ?? []).some((x) => x.code === t.timeframe);
    update(tfKnown ? { symbol: t.symbol, timeframe: t.timeframe } : { symbol: t.symbol });
    go("charts");
  }

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
        : data?.source === "alphavantage"
          ? "Alpha Vantage (LSE)"
          : "";

  return (
    <div className={page === "charts" ? "workspace fixed" : "workspace"}>
      <header className="topbar">
        <div className="brand small">
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-name">GandyTrade Lab</span>
        </div>
        <nav className="main-nav" aria-label="Sections">
          {PAGES.map((p) => (
            <a key={p.key} href={`#/${p.key}`} className={page === p.key ? "on" : ""} aria-current={page === p.key ? "page" : undefined}
              onClick={(e) => { e.preventDefault(); go(p.key); }}>
              {p.label}
            </a>
          ))}
        </nav>
        <div className="spacer" />
        <span className="mode-badge" title="No real money is involved anywhere in this version">Research · no real money</span>
        <span className="muted user">{username}</span>
        <button className="ghost" onClick={signOut}>Sign out</button>
      </header>

      {backupOverdue && (
        <div className="banner error" role="alert">
          Backups haven't worked for over two days. <a href="#/settings" onClick={(e) => { e.preventDefault(); go("settings"); }}>See Settings</a>.
        </div>
      )}
      {page === "backtest" && (
        <div className="subtabs" role="tablist" aria-label="Backtest type">
          <button type="button" role="tab" aria-selected={!basketMode} className={basketMode ? "" : "on"} onClick={() => setBasketMode(false)}>One market</button>
          <button type="button" role="tab" aria-selected={basketMode} className={basketMode ? "on" : ""} onClick={() => setBasketMode(true)}>Basket of markets</button>
        </div>
      )}
      {page === "backtest" && !basketMode && (
        <BacktestPage key={JSON.stringify(backtestInit ?? {})} catalogue={catalogue} favourites={favourites}
          onToggleFavourite={toggleFavourite} onAuthError={handleAuth} initial={backtestInit}
          onRunOnPaper={(p) => { setAutoPrefill(p); go("paper"); }} />
      )}
      {page === "backtest" && basketMode && (
        <BasketPanel key={JSON.stringify(basketInit ?? {})} catalogue={catalogue} favourites={favourites}
          onToggleFavourite={toggleFavourite} onAuthError={handleAuth} initial={basketInit}
          onStartedOnPaper={(id) => { setPaperOpen(id); go("paper"); }} />
      )}
      {page === "paper" && (
        <PaperPage onAuthError={handleAuth}
          onShowTrade={showTrade}
          onShowOrder={(o) => {
            setShownTrade(null);
            const tfKnown = (catalogue?.timeframes ?? []).some((x) => x.code === o.timeframe);
            update(tfKnown ? { symbol: o.symbol, timeframe: o.timeframe } : { symbol: o.symbol });
            go("charts");
          }}
          catalogue={catalogue} favourites={favourites} onToggleFavourite={toggleFavourite}
          autoPrefill={autoPrefill} onPrefillUsed={() => setAutoPrefill(null)}
          openAccount={paperOpen} onAccountOpened={() => setPaperOpen(null)} />
      )}
      {page === "tools" && (
        <ToolsPage catalogue={catalogue} favourites={favourites} onToggleFavourite={toggleFavourite} onAuthError={handleAuth} />
      )}
      {page === "research" && (
        <ResearchPage onAuthError={handleAuth}
          onBacktest={(r) => { setBacktestInit({ symbol: r.symbol, strategy: r.strategy, timeframe: r.timeframe, direction: r.direction, mode: "cfd", years: 0 }); setBasketMode(false); go("backtest"); }}
          onRunOnPaper={(p) => { setAutoPrefill(p); go("paper"); }}
          onBasket={(b) => { setBasketInit(b); setBasketMode(true); go("backtest"); }} />
      )}
      {page === "dashboard" && <DashboardPage onAuthError={handleAuth} />}
      {page === "review" && <ReviewPage onAuthError={handleAuth} />}
      {page === "builder" && (
        <BuilderPage onAuthError={handleAuth} onBacktest={(key) => { setBacktestInit({ strategy: key }); setBasketMode(false); go("backtest"); }} />
      )}
      {page === "replay" && (
        <ReplayPage catalogue={catalogue} favourites={favourites} onToggleFavourite={toggleFavourite} symbol={prefs.symbol}
          indicators={prefs.indicators} style={prefs.style} onAuthError={handleAuth} />
      )}
      {page === "journal" && <JournalPage onAuthError={handleAuth} onShowTrade={(t) => showTrade(t)} />}
      {page === "settings" && <SettingsPage onAuthError={handleAuth} />}
      {page === "learn" && (
        <LearnPage onBacktest={(strategy) => { setBacktestInit({ strategy }); go("backtest"); }} onGo={(p) => go(p)} onAuthError={handleAuth} />
      )}

      {page === "charts" && (<>
      <div className="toolbar" role="toolbar" aria-label="Chart settings">
        <MarketPicker
          value={prefs.symbol}
          current={data?.symbol.code === prefs.symbol ? data.symbol : catalogue?.symbols.find((x) => x.code === prefs.symbol)}
          popular={catalogue?.symbols ?? []}
          counts={catalogue?.marketCounts ?? {}}
          favourites={favourites}
          onToggleFavourite={toggleFavourite}
          onChange={(sym) => update({ symbol: sym.code })}
          onAuthError={handleAuth}
        />

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

        <button className={panel === "indicators" ? "secondary on" : "secondary"} onClick={() => setPanel((p) => (p === "indicators" ? "" : "indicators"))}
          aria-expanded={panel === "indicators"}>
          Indicators ({prefs.indicators.length})
        </button>
        <button className={panel === "plan" ? "secondary on" : "secondary"} onClick={() => setPanel((p) => (p === "plan" ? "" : "plan"))}
          aria-expanded={panel === "plan"} title="Draw a trade on the chart and see its size, risk and reward">
          Plan a trade
        </button>
        <button className={panel === "signals" ? "secondary on" : "secondary"} onClick={() => setPanel((p) => (p === "signals" ? "" : "signals"))}
          aria-expanded={panel === "signals"} title="What each strategy's rules say about this chart">
          Signals
        </button>
        <button className={panel === "calendar" ? "secondary on" : "secondary"} onClick={() => setPanel((p) => (p === "calendar" ? "" : "calendar"))}
          aria-expanded={panel === "calendar"} title="Coming interest rate decisions, inflation and jobs reports">
          Calendar{calendarSoon ? " ●" : ""}
        </button>
        <button className="ghost" onClick={() => load()} disabled={loading} title="Fetch the latest prices now">
          {loading ? "Loading…" : "Refresh"}
        </button>
        <label className="auto-refresh" title={`Updates every ${REFRESH_SECONDS[prefs.timeframe] ?? 60} seconds on this timeframe`}>
          <input type="checkbox" checked={prefs.autoRefresh} onChange={(e) => update({ autoRefresh: e.target.checked })} />
          Auto-refresh
        </label>
        {sourceLabel && <span className={data?.sample ? "source sample" : "source"}>{sourceLabel}</span>}
        {streamable && live && livePrice && (
          <span className="live-badge" title="Prices stream live from OANDA's practice feed">
            <i aria-hidden="true" /> Live {livePrice.mid.toFixed(data!.symbol.precision)}
          </span>
        )}
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
      {shownTrade?.allOnly && data?.symbol.code === shownTrade.symbol && (
        <div className="banner info trade-banner" role="status">
          Showing all {shownTrade.others?.length ?? 0} trades of {shownTrade.label || "this automatic run"} on {displayCode(shownTrade.symbol)}:
          blue arrows are entries, dots are exits (green made money, red lost), with each result beside it.{" "}
          <button type="button" className="link-button" onClick={() => go("paper")}>Back to Paper</button>{" · "}
          <button type="button" className="link-button" onClick={() => setShownTrade(null)}>Hide</button>
        </div>
      )}
      {shownTrade && !shownTrade.allOnly && data?.symbol.code === shownTrade.symbol && (
        <div className="banner info trade-banner" role="status">
          {shownTrade.others && shownTrade.others.length > 1 ? `Trade ${(shownTrade.others.findIndex((o) => o.id === shownTrade.id) + 1) || ""} of ${shownTrade.others.length} from this run (the others are marked too). ` : ""}
          Showing your {shownTrade.exitPrice != null ? "closed " : ""}paper {shownTrade.side === "long" ? "buy" : "short"} on {displayCode(shownTrade.symbol)}:
          entry {shownTrade.entryPrice.toFixed(data.symbol.precision)}, stop-loss {shownTrade.stop.toFixed(data.symbol.precision)}
          {shownTrade.target !== null ? `, target ${shownTrade.target.toFixed(data.symbol.precision)}` : ", no target"}
          {shownTrade.exitPrice != null
            ? `; closed at ${shownTrade.exitPrice.toFixed(data.symbol.precision)}${shownTrade.exitReason ? ` (${shownTrade.exitReason})` : ""}, ${(shownTrade.pnl ?? 0) >= 0 ? "+" : "−"}£${Math.abs(shownTrade.pnl ?? 0).toFixed(2)}`
            : ""}.{" "}
          <button type="button" className="link-button" onClick={() => go("paper")}>Back to Paper</button>{" · "}
          <button type="button" className="link-button" onClick={() => setShownTrade(null)}>Hide</button>
        </div>
      )}

      {page === "charts" && calendarSoon && (
        <div className="banner event-soon" role="status">
          <b>{calendarSoon.title}</b> {inWords(calendarSoon.inSeconds)}
          {" "}({new Date(calendarSoon.time * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" })} UK{calendarSoon.approx ? ", roughly" : ""}).
          {" "}Prices can jump and spreads widen around it.{" "}
          <button type="button" className="link-button" onClick={() => setPanel("calendar")}>Calendar</button>
        </div>
      )}
      <div className={panel ? `body with-panel ${panel}` : "body"}>
        <section className="chart-area" aria-busy={loading}>
          {data && data.bars.length > 0 ? (
            <ChartView data={data} live={livePrice} plan={panel === "plan" && data.symbol.code === prefs.symbol ? plan : null} onPlanChange={changePlan}
              trade={shownTrade && data.symbol.code === shownTrade.symbol ? shownTrade : null}
              orders={data.symbol.code === prefs.symbol ? priceOrders : []}
              markers={calendarMarks.markers} notes={calendarMarks.notes} />
          ) : !error && <div className="splash">Loading chart…</div>}
        </section>

        {panel === "plan" && data && (
          <aside className="panel" aria-label="Trade planner">
            <TradePlanner symbol={data.symbol} timeframe={prefs.timeframe} plan={plan} onPlanChange={changePlan} onStartFresh={startPlan}
              linked={linked} onLinkedChange={setLinked}
              onAuthError={handleAuth} onPlaced={loadOrders} lastPrice={livePrice?.mid ?? lastClose} eventSoon={calendarSoon}
              orders={priceOrders} onOrdersChanged={loadOrders} />
          </aside>
        )}
        {panel === "calendar" && (
          <aside className="panel" aria-label="Economic calendar">
            <CalendarPanel symbol={prefs.symbol} onAuthError={handleAuth} />
          </aside>
        )}
        {panel === "signals" && (
          <aside className="panel" aria-label="Signal assistant">
            <SignalPanel symbol={prefs.symbol} timeframe={prefs.timeframe} lastBarTime={data?.bars[data.bars.length - 1]?.time}
              precision={data?.symbol.precision ?? 5} onAuthError={handleAuth}
              onShowPlan={(p) => { setPlan(p); setPanel("plan"); }}
              onBacktest={(strategy) => {
                setBacktestInit({ strategy, symbol: prefs.symbol, timeframe: ["1h", "4h", "1d", "1w"].includes(prefs.timeframe) ? prefs.timeframe : "1d" });
                go("backtest");
              }} />
          </aside>
        )}
        {panel === "indicators" && catalogue && (
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
      </>)}

      <footer className="footer">
        <span>Educational use only. Not financial advice.</span>
        <span>
          Charts by <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">TradingView</a> Lightweight Charts™
        </span>
      </footer>
    </div>
  );
}
