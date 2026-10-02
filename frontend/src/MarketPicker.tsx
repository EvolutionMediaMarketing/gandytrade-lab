import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { SymbolInfo } from "./types";

export const CLASS_LABELS: Record<string, string> = {
  forex: "Forex",
  metal: "Metals",
  commodity: "Commodities",
  index: "Indices",
  bond: "Bonds",
  ukstock: "UK shares",
  stock: "US stocks",
  etf: "US ETFs",
};
const CLASS_ORDER = ["forex", "metal", "commodity", "index", "bond", "ukstock", "stock", "etf"];
const FAVS = "favourites";
const RECENT_STORAGE_SLOT = "gt.recentMarkets.v1";
const MAX_RECENT = 8;

function loadRecent(): SymbolInfo[] {
  try {
    const raw = localStorage.getItem(RECENT_STORAGE_SLOT);
    return raw ? (JSON.parse(raw) as SymbolInfo[]).slice(0, MAX_RECENT) : [];
  } catch {
    return [];
  }
}

function saveRecent(list: SymbolInfo[]) {
  try {
    localStorage.setItem(RECENT_STORAGE_SLOT, JSON.stringify(list.slice(0, MAX_RECENT)));
  } catch {
    /* storage unavailable */
  }
}

export const displayCode = (code: string) => (code.includes("_") ? code.replace("_", "/") : code);

interface Props {
  value: string;
  current?: SymbolInfo;
  popular: SymbolInfo[];
  counts: Record<string, number>;
  favourites: SymbolInfo[];
  onToggleFavourite: (s: SymbolInfo, on: boolean) => void;
  onChange: (s: SymbolInfo) => void;
  onAuthError: (err: unknown) => void;
}

type Row = { kind: "heading"; label: string } | { kind: "item"; symbol: SymbolInfo };

export default function MarketPicker({ value, current, popular, counts, favourites, onToggleFavourite, onChange, onAuthError }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cls, setCls] = useState("");
  const [results, setResults] = useState<SymbolInfo[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [active, setActive] = useState(0);
  const [recent, setRecent] = useState<SymbolInfo[]>(loadRecent);
  const wrap = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);

  const total = useMemo(() => Object.values(counts).reduce((a, b) => a + b, 0), [counts]);
  const favSet = useMemo(() => new Set(favourites.map((f) => f.code)), [favourites]);
  const showingFavs = cls === FAVS;
  const browsing = !query.trim() && !cls;
  const serverSearch = open && !browsing && !showingFavs;

  // Search on the server as you type (short pause first so we don't send a request per key).
  useEffect(() => {
    if (!serverSearch) {
      setResults(null);
      return;
    }
    const ctrl = new AbortController();
    setSearching(true);
    const timer = window.setTimeout(() => {
      api
        .searchMarkets(query.trim(), cls, ctrl.signal)
        .then((r) => {
          setResults(r.results);
          setActive(0);
        })
        .catch((err) => {
          if (err instanceof ApiError && err.status === 401) onAuthError(err);
        })
        .finally(() => setSearching(false));
    }, 180);
    return () => {
      ctrl.abort();
      window.clearTimeout(timer);
    };
  }, [serverSearch, query, cls, onAuthError]);

  // Close when clicking elsewhere.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      window.setTimeout(() => input.current?.focus(), 0);
    }
  }, [open]);

  const rows: Row[] = useMemo(() => {
    if (showingFavs) {
      const q = query.trim().toLowerCase().replace("/", "_");
      return favourites
        .filter((s) => !q || `${s.code} ${s.name}`.toLowerCase().includes(q))
        .map((symbol) => ({ kind: "item" as const, symbol }));
    }
    if (!browsing) return (results ?? []).map((symbol) => ({ kind: "item" as const, symbol }));
    const out: Row[] = [];
    if (favourites.length) {
      out.push({ kind: "heading", label: "Favourites" });
      favourites.forEach((symbol) => out.push({ kind: "item", symbol }));
    }
    if (recent.length) {
      out.push({ kind: "heading", label: "Recent" });
      recent.forEach((symbol) => out.push({ kind: "item", symbol }));
    }
    for (const c of CLASS_ORDER) {
      const group = popular.filter((s) => s.asset_class === c);
      if (!group.length) continue;
      out.push({ kind: "heading", label: `Popular ${CLASS_LABELS[c] ?? c}` });
      group.forEach((symbol) => out.push({ kind: "item", symbol }));
    }
    return out;
  }, [browsing, showingFavs, query, results, recent, popular, favourites]);

  const items = rows.filter((r): r is Extract<Row, { kind: "item" }> => r.kind === "item");

  function choose(symbol: SymbolInfo) {
    const next = [symbol, ...recent.filter((r) => r.code !== symbol.code)].slice(0, MAX_RECENT);
    setRecent(next);
    saveRecent(next);
    onChange(symbol);
    setOpen(false);
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      setOpen(false);
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const n = items.length;
      if (!n) return;
      const next = (active + (e.key === "ArrowDown" ? 1 : -1) + n) % n;
      setActive(next);
      list.current?.querySelector(`[data-index="${next}"]`)?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter" && items[active]) {
      e.preventDefault();
      choose(items[active].symbol);
    }
  }

  let itemIndex = -1;
  const label = current && current.code === value ? current.name : "";

  return (
    <div className="market-picker" ref={wrap}>
      <span className="field-label">Market</span>
      <button
        type="button"
        className="market-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <b>{displayCode(value)}</b>
        {label && <span className="muted">{label}</span>}
        <span className="caret" aria-hidden="true">▾</span>
      </button>
      {current && current.code === value && (
        <button
          type="button"
          className={favSet.has(value) ? "star trigger-star on" : "star trigger-star"}
          title={favSet.has(value) ? "Remove from favourites" : "Add to favourites"}
          aria-label={favSet.has(value) ? `Remove ${current.name} from favourites` : `Add ${current.name} to favourites`}
          aria-pressed={favSet.has(value)}
          onClick={() => onToggleFavourite(current, !favSet.has(value))}
        >
          {favSet.has(value) ? "★" : "☆"}
        </button>
      )}

      {open && (
        <div className="market-pop" role="dialog" aria-label="Choose a market" onKeyDown={onKey}>
          <input
            ref={input}
            className="market-search"
            type="search"
            value={query}
            placeholder={`Search ${total ? total.toLocaleString("en-GB") + " " : ""}markets by code or name`}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search markets"
            aria-controls="market-results"
            autoComplete="off"
            spellCheck={false}
          />
          <div className="class-chips" role="group" aria-label="Filter by type">
            <button type="button" className={!cls ? "on" : ""} onClick={() => setCls("")}>All</button>
            <button type="button" className={showingFavs ? "on" : ""} onClick={() => setCls(showingFavs ? "" : FAVS)}>
              ★ Favourites <span className="count">{favourites.length}</span>
            </button>
            {CLASS_ORDER.filter((c) => counts[c]).map((c) => (
              <button key={c} type="button" className={cls === c ? "on" : ""} onClick={() => setCls(cls === c ? "" : c)}>
                {CLASS_LABELS[c]} <span className="count">{counts[c].toLocaleString("en-GB")}</span>
              </button>
            ))}
          </div>

          <ul className="market-list" id="market-results" role="listbox" ref={list}>
            {rows.map((row, i) => {
              if (row.kind === "heading") return <li key={`h-${row.label}-${i}`} className="list-heading" role="presentation">{row.label}</li>;
              itemIndex += 1;
              const idx = itemIndex;
              const s = row.symbol;
              return (
                <li
                  key={`${s.code}-${i}`}
                  role="option"
                  data-index={idx}
                  aria-selected={idx === active}
                  className={`${idx === active ? "active" : ""} ${s.code === value ? "current" : ""}`}
                  onMouseEnter={() => setActive(idx)}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => choose(s)}
                >
                  <span className="m-code">{displayCode(s.code)}</span>
                  <span className="m-name">{s.name}</span>
                  <span className="tag">{CLASS_LABELS[s.asset_class] ?? s.asset_class}</span>
                  <button
                    type="button"
                    className={favSet.has(s.code) ? "star on" : "star"}
                    aria-label={favSet.has(s.code) ? `Remove ${s.name} from favourites` : `Add ${s.name} to favourites`}
                    aria-pressed={favSet.has(s.code)}
                    onClick={(e) => {
                      e.stopPropagation();
                      onToggleFavourite(s, !favSet.has(s.code));
                    }}
                  >
                    {favSet.has(s.code) ? "★" : "☆"}
                  </button>
                </li>
              );
            })}
            {showingFavs && rows.length === 0 && (
              <li className="list-empty" role="presentation">
                {favourites.length ? `No favourites match “${query}”.` : "No favourites yet. Tap ☆ next to any market to add it."}
              </li>
            )}
            {serverSearch && !searching && results && results.length === 0 && (
              <li className="list-empty" role="presentation">No markets match “{query}”.</li>
            )}
            {serverSearch && searching && !results && <li className="list-empty" role="presentation">Searching…</li>}
          </ul>
          {results && results.length >= 60 && (
            <p className="list-foot muted">Showing the first 60. Type more to narrow it down.</p>
          )}
        </div>
      )}
    </div>
  );
}
