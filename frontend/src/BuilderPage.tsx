import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { BuilderCatalogue, BuilderCondition, BuilderOperand, BuilderSpec, BuilderStrategy } from "./types";

const EMPTY: BuilderSpec = {
  name: "", description: "",
  long: { enabled: true, entry: [], exit: [] },
  short: { enabled: false, entry: [], exit: [] },
  stop: { type: "atr", value: 2, length: 10 },
  target: { type: "none", value: 2 },
};

/** Ready-made starting points: pick one, then change anything. */
const TEMPLATES: { label: string; spec: BuilderSpec }[] = [
  {
    label: "Above the cloud, buy an RSI dip",
    spec: {
      ...EMPTY, name: "Cloud and RSI dip", description: "In an uptrend (price above the Ichimoku cloud), buy when RSI dips below 40.",
      long: {
        enabled: true,
        entry: [
          { left: { type: "close" }, op: "above", right: { type: "cloud_top" } },
          { left: { type: "rsi", length: 14 }, op: "below", right: { type: "number", value: 40 } },
        ],
        exit: [{ left: { type: "close" }, op: "below", right: { type: "cloud_bottom" } }],
      },
    },
  },
  {
    label: "200-average trend, 20/50 cross",
    spec: {
      ...EMPTY, name: "Trend cross", description: "Buy when the 20 EMA crosses above the 50 EMA while price is above the 200 average.",
      long: {
        enabled: true,
        entry: [
          { left: { type: "ema", length: 20 }, op: "crosses_above", right: { type: "ema", length: 50 } },
          { left: { type: "close" }, op: "above", right: { type: "sma", length: 200 } },
        ],
        exit: [{ left: { type: "ema", length: 20 }, op: "crosses_below", right: { type: "ema", length: 50 } }],
      },
    },
  },
  {
    label: "Breakout (your own version)",
    spec: {
      ...EMPTY, name: "My breakout", description: "Buy a close above the highest high of the last 55 candles; sell below the lowest low of the last 20.",
      long: {
        enabled: true,
        entry: [{ left: { type: "close" }, op: "above", right: { type: "highest", length: 55 } }],
        exit: [{ left: { type: "close" }, op: "below", right: { type: "lowest", length: 20 } }],
      },
    },
  },
];

/** The strategy builder: your own rules from blocks, usable everywhere the built-in strategies are. */
export default function BuilderPage({ onAuthError, onBacktest }: { onAuthError: (err: unknown) => void; onBacktest: (key: string) => void }) {
  const [cat, setCat] = useState<BuilderCatalogue | null>(null);
  const [mine, setMine] = useState<BuilderStrategy[]>([]);
  const [editing, setEditing] = useState<BuilderStrategy | null>(null); // null + spec = new
  const [spec, setSpec] = useState<BuilderSpec | null>(null);
  const [preview, setPreview] = useState<string[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.builderList().then((r) => setMine(r.strategies)).catch(onAuthError);
  }, [onAuthError]);
  useEffect(() => {
    api.builderCatalogue().then(setCat).catch(onAuthError);
    load();
  }, [load, onAuthError]);

  // The rules in plain words, checked by the server as you edit (a short pause so typing doesn't flood it).
  useEffect(() => {
    if (!spec) return;
    const t = window.setTimeout(() => {
      api.builderCheck(spec).then((r) => { setPreview(r.rules); setProblem(null); })
        .catch((err) => { setPreview(null); setProblem(err instanceof Error ? err.message : "Not valid yet."); });
    }, 350);
    return () => window.clearTimeout(t);
  }, [spec]);

  function open(s: BuilderStrategy | null, fresh?: BuilderSpec) {
    setEditing(s);
    setSpec(s ? structuredClone(s.spec) : structuredClone(fresh ?? EMPTY));
    setError(null);
    setSaved(null);
  }

  function save(asNew: boolean) {
    if (!spec) return;
    setBusy(true);
    setError(null);
    setSaved(null);
    const p = editing && !asNew ? api.builderUpdate(editing.id, spec) : api.builderCreate(asNew && editing ? { ...spec, name: `${spec.name} (copy)`.slice(0, 60) } : spec);
    p.then((s) => { setEditing(s); setSpec(structuredClone(s.spec)); setSaved(`Saved “${s.name}”. It's now in every strategy list: Backtest, Research, automatic runs, Replay and Signals.`); load(); })
      .catch((err) => { onAuthError(err); setError(err instanceof Error ? err.message : "It wasn't saved."); })
      .finally(() => setBusy(false));
  }

  return (
    <div className="page builder">
      <aside className="builder-list card">
        <h2>Your strategies</h2>
        {mine.length === 0 && <p className="muted small-text">None yet. Start from a template or a blank page.</p>}
        <ul>
          {mine.map((s) => (
            <li key={s.id}>
              <button type="button" className={`acct ${editing?.id === s.id ? "on" : ""}`} onClick={() => open(s)}>
                <span className="acct-name">{s.name}</span>
                <span className="muted small-text">{s.runs ? `${s.runs} automatic run${s.runs === 1 ? "" : "s"}` : "Not running"}</span>
              </button>
            </li>
          ))}
        </ul>
        <h3>Start a new one</h3>
        <button type="button" className="ghost small" onClick={() => open(null)}>Blank</button>
        {TEMPLATES.map((t) => <button key={t.label} type="button" className="ghost small" onClick={() => open(null, t.spec)}>{t.label}</button>)}
      </aside>

      <section className="builder-main">
        {!spec || !cat ? (
          <div className="card empty-state">
            <h2>Build your own strategy</h2>
            <p className="muted">
              Put rules together from blocks: price, averages, RSI, MACD, Bollinger Bands, ADX and the Ichimoku cloud. For example,
              “close above the cloud and RSI below 40 → buy; stop 2 × ATR; exit when the close drops below the cloud”.
              Once saved, it works everywhere the built-in strategies do: backtests, the walk-forward check, research scans,
              automatic paper runs, replay and the signal assistant.
            </p>
            <p className="muted small-text">Pick a template on the left to see how one is put together.</p>
          </div>
        ) : (
          <div className="card builder-form">
            <div className="param-grid">
              <label><span>Name</span><input maxLength={60} value={spec.name} onChange={(e) => setSpec({ ...spec, name: e.target.value })} placeholder="e.g. Cloud and RSI dip" /></label>
              <label className="wide"><span>What it's for (optional)</span><input maxLength={500} value={spec.description}
                onChange={(e) => setSpec({ ...spec, description: e.target.value })} placeholder="The idea in a sentence" /></label>
            </div>

            {(["long", "short"] as const).map((side) => (
              <SideEditor key={side} side={side} cat={cat} value={spec[side]} max={cat.maxConditions}
                onChange={(v) => setSpec({ ...spec, [side]: v })} />
            ))}

            <div className="builder-block">
              <h3>Stop-loss <span className="muted small-text">(every trade has one)</span></h3>
              <div className="builder-row">
                <select value={spec.stop.type} onChange={(e) => setSpec({ ...spec, stop: { ...spec.stop, type: e.target.value as BuilderSpec["stop"]["type"] } })}>
                  <option value="atr">A multiple of ATR (the typical candle range)</option>
                  <option value="percent">A percentage of the price</option>
                  <option value="swing">The recent swing low (buys) or high (shorts)</option>
                </select>
                {spec.stop.type === "swing"
                  ? <label className="inline">over <input type="number" min={2} max={200} value={spec.stop.length ?? 10}
                      onChange={(e) => setSpec({ ...spec, stop: { ...spec.stop, length: Number(e.target.value) } })} /> candles</label>
                  : <label className="inline"><input type="number" step={spec.stop.type === "atr" ? 0.1 : 0.05} value={spec.stop.value ?? 2}
                      onChange={(e) => setSpec({ ...spec, stop: { ...spec.stop, value: Number(e.target.value) } })} />
                      {spec.stop.type === "atr" ? "× ATR" : "%"}</label>}
              </div>
            </div>
            <div className="builder-block">
              <h3>Target <span className="muted small-text">(optional)</span></h3>
              <div className="builder-row">
                <select value={spec.target.type} onChange={(e) => setSpec({ ...spec, target: { ...spec.target, type: e.target.value as "none" | "r" } })}>
                  <option value="none">None: the exit rules or the stop close the trade</option>
                  <option value="r">A multiple of the risk (R)</option>
                </select>
                {spec.target.type === "r" && <label className="inline"><input type="number" step={0.25} min={0.25} value={spec.target.value ?? 2}
                  onChange={(e) => setSpec({ ...spec, target: { ...spec.target, value: Number(e.target.value) } })} /> R</label>}
              </div>
            </div>

            <div className="builder-preview">
              <h3>In plain words</h3>
              {problem ? <p className="warn caution">{problem}</p> : preview ? <ol>{preview.map((r, i) => <li key={i}>{r}</li>)}</ol> : <p className="muted">Checking…</p>}
              <p className="muted small-text">Rules are checked on each finished candle; trades open at the next candle's open. Every length you choose becomes a
                setting the walk-forward check can tune; levels like “RSI below 40” stay as you set them.</p>
            </div>

            {error && <p className="warn stop">{error}</p>}
            {saved && <p className="note">{saved}</p>}
            <div className="planner-actions">
              <button type="button" className="primary" disabled={busy || !!problem} onClick={() => save(false)}>{editing ? "Save changes" : "Save strategy"}</button>
              {editing && <button type="button" className="ghost" disabled={busy || !!problem} onClick={() => save(true)}>Save as a new copy</button>}
              {editing && <button type="button" className="ghost" onClick={() => onBacktest(editing.key)}>Backtest it</button>}
              {editing && (
                <button type="button" className="link-button danger-link" onClick={() => {
                  if (!window.confirm(`Delete “${editing.name}”? Backtests already run with it keep their results.`)) return;
                  api.builderDelete(editing.id).then(() => { setEditing(null); setSpec(null); load(); })
                    .catch((err) => { onAuthError(err); setError(err instanceof Error ? err.message : "It wasn't deleted."); });
                }}>Delete</button>
              )}
            </div>
            {editing && editing.runs > 0 && <p className="muted small-text">An automatic run is using this strategy, so its rules can't change until you stop it. “Save as a new copy” works any time.</p>}
            <p className="muted small-text">A new strategy is an untested idea. Backtest it on several markets and run the walk-forward check before giving it a paper account.</p>
          </div>
        )}
      </section>
    </div>
  );
}

function SideEditor({ side, cat, value, max, onChange }: {
  side: "long" | "short"; cat: BuilderCatalogue; value: BuilderSpec["long"]; max: number; onChange: (v: BuilderSpec["long"]) => void;
}) {
  const word = side === "long" ? "Buy" : "Short (sell)";
  const blank: BuilderCondition = { left: { type: "close" }, op: "above", right: { type: "sma", length: 50 } };
  return (
    <div className={`builder-block ${value.enabled ? "" : "off"}`}>
      <h3>
        <label className="check-row"><input type="checkbox" checked={value.enabled} onChange={(e) => onChange({ ...value, enabled: e.target.checked })} />
          {word} rules</label>
        {side === "short" && <span className="muted small-text"> (needs a CFD / spread bet account; your backtests found shorts lost money)</span>}
      </h3>
      {value.enabled && (
        <>
          <h4>Enter when <b>all</b> of these are true</h4>
          {value.entry.map((c, i) => (
            <ConditionRow key={i} cat={cat} value={c} onChange={(v) => onChange({ ...value, entry: value.entry.map((x, k) => (k === i ? v : x)) })}
              onRemove={() => onChange({ ...value, entry: value.entry.filter((_, k) => k !== i) })} />
          ))}
          {value.entry.length < max && <button type="button" className="link-button" onClick={() => onChange({ ...value, entry: [...value.entry, structuredClone(blank)] })}>+ Add a rule</button>}
          <h4>Exit when <b>any</b> of these is true <span className="muted small-text">(optional: the stop and target close trades too)</span></h4>
          {value.exit.map((c, i) => (
            <ConditionRow key={i} cat={cat} value={c} onChange={(v) => onChange({ ...value, exit: value.exit.map((x, k) => (k === i ? v : x)) })}
              onRemove={() => onChange({ ...value, exit: value.exit.filter((_, k) => k !== i) })} />
          ))}
          {value.exit.length < max && <button type="button" className="link-button" onClick={() => onChange({ ...value, exit: [...value.exit, structuredClone(blank)] })}>+ Add an exit rule</button>}
        </>
      )}
    </div>
  );
}

function ConditionRow({ cat, value, onChange, onRemove }: {
  cat: BuilderCatalogue; value: BuilderCondition; onChange: (v: BuilderCondition) => void; onRemove: () => void;
}) {
  const needsRight = cat.ops.find((o) => o.op === value.op)?.needsRight ?? true;
  return (
    <div className="builder-row condition">
      <OperandPicker cat={cat} value={value.left} allowNumber={false} onChange={(left) => onChange({ ...value, left })} />
      <select value={value.op} aria-label="Comparison" onChange={(e) => {
        const op = e.target.value;
        const needs = cat.ops.find((o) => o.op === op)?.needsRight ?? true;
        onChange({ ...value, op, right: needs ? value.right ?? { type: "number", value: 0 } : null });
      }}>
        {cat.ops.map((o) => <option key={o.op} value={o.op}>{o.label}</option>)}
      </select>
      {needsRight && value.right && <OperandPicker cat={cat} value={value.right} allowNumber onChange={(right) => onChange({ ...value, right })} />}
      <button type="button" className="ghost small" aria-label="Remove this rule" onClick={onRemove}>×</button>
    </div>
  );
}

function OperandPicker({ cat, value, allowNumber, onChange }: {
  cat: BuilderCatalogue; value: BuilderOperand; allowNumber: boolean; onChange: (v: BuilderOperand) => void;
}) {
  const groups = useMemo(() => {
    const g = new Map<string, BuilderCatalogue["operands"]>();
    for (const o of cat.operands) {
      if (o.type === "number" && !allowNumber) continue;
      g.set(o.group, [...(g.get(o.group) ?? []), o]);
    }
    return [...g.entries()];
  }, [cat, allowNumber]);
  const def = cat.operands.find((o) => o.type === value.type);
  return (
    <span className="operand">
      <select value={value.type} aria-label="What to compare" onChange={(e) => {
        const t = e.target.value;
        const d = cat.operands.find((o) => o.type === t);
        const next: BuilderOperand = { type: t };
        for (const l of d?.lengths ?? []) next[l.name] = l.default;
        if (t === "number") next.value = 0;
        onChange(next);
      }}>
        {groups.map(([group, list]) => (
          <optgroup key={group} label={group}>
            {list.map((o) => <option key={o.type} value={o.type}>{o.label}</option>)}
          </optgroup>
        ))}
      </select>
      {value.type === "number" && <input type="number" step="any" className="num-in" value={Number(value.value ?? 0)}
        onChange={(e) => onChange({ ...value, value: Number(e.target.value) })} />}
      {(def?.lengths ?? []).map((l) => (
        <label key={l.name} className="inline" title={l.label}>
          <span className="muted small-text">{l.label.toLowerCase()}</span>
          <input type="number" className="num-in" min={l.min} max={l.max} value={Number(value[l.name] ?? l.default)}
            onChange={(e) => onChange({ ...value, [l.name]: Number(e.target.value) })} />
        </label>
      ))}
    </span>
  );
}
