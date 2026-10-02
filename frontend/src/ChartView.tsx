import { useCallback, useEffect, useRef, useState } from "react";
import {
  AreaSeries,
  BarSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  IChartApi,
  IPriceLine,
  ISeriesApi,
  LineSeries,
  LineStyle,
  SeriesType,
  Time,
  SeriesMarker,
  TickMarkType,
  createChart,
  createSeriesMarkers,
} from "lightweight-charts";
import { BandFill } from "./BandFill";
import { PlanZones, TradePlan } from "./PlanZones";
import type { BarData, ChartData } from "./types";

const C = {
  bg: "#0d131a",
  grid: "#1a242f",
  text: "#9fb0c0",
  up: "#34d399",
  down: "#f87171",
  upSoft: "rgba(52, 211, 153, 0.35)",
  downSoft: "rgba(248, 113, 113, 0.35)",
};

// One colour per indicator line, chosen to stay readable on the dark chart.
const LINE_COLOURS: Record<string, string> = {
  sma: "#fbbf24",
  ema: "#60a5fa",
  vwap: "#f472b6",
  upper: "#a78bfa",
  basis: "#c4b5fd",
  lower: "#a78bfa",
  tenkan: "#38bdf8",
  kijun: "#f97316",
  lead_a: "#34d399",
  lead_b: "#f87171",
  lagging: "#a3a3a3",
  rsi: "#c084fc",
  macd: "#60a5fa",
  signal: "#fb923c",
  k: "#60a5fa",
  d: "#fb923c",
  atr: "#2dd4bf",
};

// Relative heights: the price pane is 1, each indicator pane a fraction of it.
const SUB_PANE_SHARE = 0.3;
const VOLUME_PANE_SHARE = 0.2;

function priceFormat(precision: number) {
  return { type: "price" as const, precision, minMove: Math.pow(10, -precision) };
}

function fmt(v: number | undefined, precision: number) {
  return v === undefined ? "–" : v.toFixed(precision);
}

// Show times in the viewer's own time zone (UK time for you), not UTC.
function tickLabel(seconds: number, type: TickMarkType): string {
  const d = new Date(seconds * 1000);
  switch (type) {
    case TickMarkType.Year:
      return d.toLocaleDateString("en-GB", { year: "numeric" });
    case TickMarkType.Month:
      return d.toLocaleDateString("en-GB", { month: "short" });
    case TickMarkType.DayOfMonth:
      return d.toLocaleDateString("en-GB", { day: "numeric" });
    case TickMarkType.TimeWithSeconds:
      return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    default:
      return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  }
}

function crosshairLabel(seconds: number, timeframe: string): string {
  const d = new Date(seconds * 1000);
  const intraday = timeframe.endsWith("m") || timeframe.endsWith("h");
  return intraday
    ? d.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "2-digit", hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}

export type ChartMarker = SeriesMarker<Time>;

type PlanKey = "entry" | "stop" | "target";
const PLAN_STYLE: Record<PlanKey, { color: string; title: string }> = {
  entry: { color: "#60a5fa", title: "Entry" },
  stop: { color: "#f87171", title: "Stop-loss" },
  target: { color: "#34d399", title: "Target" },
};

interface ChartViewProps {
  data: ChartData;
  markers?: ChartMarker[];
  focusTime?: number;
  /** A trade plan drawn as draggable lines. */
  plan?: TradePlan | null;
  onPlanChange?: (plan: TradePlan) => void;
}

export default function ChartView({ data, markers, focusTime, plan, onPlanChange }: ChartViewProps) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const mainRef = useRef<ISeriesApi<SeriesType> | null>(null);
  const zonesRef = useRef<PlanZones | null>(null);
  const linesRef = useRef<Partial<Record<PlanKey, IPriceLine>>>({});
  const planRef = useRef<TradePlan | null | undefined>(plan);
  const onPlanChangeRef = useRef(onPlanChange);
  planRef.current = plan;
  onPlanChangeRef.current = onPlanChange;

  // Draw (or remove) the plan's lines and shading on the current chart.
  const syncPlan = useCallback(() => {
    const main = mainRef.current;
    const zones = zonesRef.current;
    if (!main || !zones) return;
    const p = planRef.current;
    const lines = linesRef.current;
    (Object.keys(PLAN_STYLE) as PlanKey[]).forEach((key) => {
      const price = p ? (key === "target" ? p.target : p[key]) : null;
      const existing = lines[key];
      if (price === null || price === undefined || !Number.isFinite(price)) {
        if (existing) main.removePriceLine(existing);
        delete lines[key];
        return;
      }
      if (existing) existing.applyOptions({ price });
      else lines[key] = main.createPriceLine({
        price, color: PLAN_STYLE[key].color, lineWidth: 2, lineStyle: key === "entry" ? LineStyle.Solid : LineStyle.Dashed,
        axisLabelVisible: true, title: PLAN_STYLE[key].title,
      });
    });
    // Shade the plan over the last 40 candles and on to the right edge, so it's easy to see.
    const n = data.bars.length;
    zones.setPlan(p ?? null, n ? data.bars[Math.max(0, n - 40)].time : null);
  }, [data]);

  useEffect(() => {
    syncPlan();
  }, [plan, syncPlan]);
  // Remembers where you'd scrolled and zoomed, so an automatic refresh doesn't reset the view.
  const viewRef = useRef<{ key: string; fromEnd: number; toEnd: number } | null>(null);
  const [legend, setLegend] = useState<BarData | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const precision = data.symbol.precision;
    const chart = createChart(host.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: C.bg },
        textColor: C.text,
        fontFamily: "'IBM Plex Sans', system-ui, sans-serif",
        attributionLogo: true,
        panes: { separatorColor: "#223040", enableResize: true },
      },
      grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: C.grid },
      timeScale: {
        borderColor: C.grid,
        timeVisible: data.timeframe.endsWith("m") || data.timeframe.endsWith("h"),
        rightOffset: 4,
        tickMarkFormatter: (time: Time, type: TickMarkType) => tickLabel(time as number, type),
      },
      localization: { locale: "en-GB", timeFormatter: (time: Time) => crosshairLabel(time as number, data.timeframe) },
    });
    chartRef.current = chart;

    // Main price series in the chosen style.
    let main: ISeriesApi<SeriesType>;
    const ohlc = data.bars.map((b) => ({ time: b.time as Time, open: b.open, high: b.high, low: b.low, close: b.close }));
    const closes = data.bars.map((b) => ({ time: b.time as Time, value: b.close }));
    const future = data.futureTimes.map((t) => ({ time: t as Time }));
    if (data.style === "line") {
      main = chart.addSeries(LineSeries, { color: "#e5edf5", lineWidth: 2, priceFormat: priceFormat(precision) });
      main.setData([...closes, ...future]);
    } else if (data.style === "area") {
      main = chart.addSeries(AreaSeries, {
        lineColor: "#60a5fa", topColor: "rgba(96,165,250,0.35)", bottomColor: "rgba(96,165,250,0.02)",
        priceFormat: priceFormat(precision),
      });
      main.setData([...closes, ...future]);
    } else if (data.style === "bars") {
      main = chart.addSeries(BarSeries, { upColor: C.up, downColor: C.down, priceFormat: priceFormat(precision) });
      main.setData([...ohlc, ...future]);
    } else {
      main = chart.addSeries(CandlestickSeries, {
        upColor: C.up, downColor: C.down, borderVisible: false, wickUpColor: C.up, wickDownColor: C.down,
        priceFormat: priceFormat(precision),
      });
      main.setData([...ohlc, ...future]);
    }

    // Trade plan: shaded zones plus draggable lines (drawn by syncPlan).
    const zones = new PlanZones();
    main.attachPrimitive(zones);
    mainRef.current = main;
    zonesRef.current = zones;
    linesRef.current = {};

    // Trade markers from a backtest (buy, sell, exit), sorted by time as the library requires.
    if (markers && markers.length) {
      const first = data.bars.length ? data.bars[0].time : 0;
      createSeriesMarkers(main, [...markers].filter((m) => (m.time as number) >= first).sort((a, b) => (a.time as number) - (b.time as number)));
    }

    // Indicators: price overlays share pane 0; each other kind gets its own pane.
    const paneIndex = new Map<string, number>([["price", 0]]);
    for (const ind of data.indicators) {
      if (ind.note || ind.lines.length === 0) continue;
      if (!paneIndex.has(ind.pane)) paneIndex.set(ind.pane, paneIndex.size);
      const pane = paneIndex.get(ind.pane)!;
      const created = new Map<string, ISeriesApi<SeriesType>>();
      const barDir = new Map(data.bars.map((b) => [b.time, b.close >= b.open]));

      for (const line of ind.lines) {
        let s: ISeriesApi<SeriesType>;
        if (line.kind === "histogram") {
          const isVolume = ind.type === "volume";
          s = chart.addSeries(
            HistogramSeries,
            {
              priceFormat: isVolume ? { type: "volume" } : priceFormat(precision + 2),
              priceLineVisible: false,
              lastValueVisible: !isVolume,
            },
            pane,
          );
          s.setData(
            line.values.map((p) => ({
              time: p.time as Time,
              value: p.value,
              color: isVolume
                ? (barDir.get(p.time) ? C.upSoft : C.downSoft)
                : p.value >= 0 ? C.upSoft : C.downSoft,
            })),
          );
        } else {
          const ichimokuLead = line.key === "lead_a" || line.key === "lead_b";
          s = chart.addSeries(
            LineSeries,
            {
              color: LINE_COLOURS[line.key] ?? "#e5edf5",
              lineWidth: ichimokuLead || line.key === "lagging" ? 1 : 2,
              lineStyle: line.key === "basis" ? LineStyle.Dashed : LineStyle.Solid,
              priceLineVisible: false,
              lastValueVisible: pane !== 0,
              crosshairMarkerVisible: false,
              priceFormat: ind.pane === "price" ? priceFormat(precision) : { type: "price", precision: 2, minMove: 0.01 },
              title: pane === 0 ? "" : line.label,
            },
            pane,
          );
          s.setData(line.values.map((p) => ({ time: p.time as Time, value: p.value })));
        }
        created.set(line.key, s);
      }

      // Reference levels such as RSI 70 / 30.
      const first = ind.lines.find((l) => l.kind !== "histogram");
      const levelHost = first ? created.get(first.key) : undefined;
      for (const level of ind.levels) {
        levelHost?.createPriceLine({
          price: level, color: "#3b4b5c", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "",
        });
      }

      // Cloud and band shading.
      if (ind.fill) {
        const upper = ind.lines.find((l) => l.key === ind.fill!.upper);
        const lower = ind.lines.find((l) => l.key === ind.fill!.lower);
        const anchor = created.get(ind.fill.upper);
        if (upper && lower && anchor) {
          anchor.attachPrimitive(
            new BandFill(
              upper.values,
              lower.values,
              ind.fill.twoTone
                ? { up: "rgba(52, 211, 153, 0.14)", down: "rgba(248, 113, 113, 0.14)" }
                : { up: "rgba(167, 139, 250, 0.08)", down: "rgba(167, 139, 250, 0.08)" },
              !!ind.fill.twoTone,
            ),
          );
        }
      }
    }

    // Share the height: the price pane gets the most, each indicator pane a fixed share.
    const panes = chart.panes();
    const paneKinds = [...paneIndex.entries()].sort((a, b) => a[1] - b[1]).map(([kind]) => kind);
    panes.forEach((pane, i) => {
      const kind = paneKinds[i];
      pane.setStretchFactor(i === 0 ? 1 : kind === "volume" ? VOLUME_PANE_SHARE : SUB_PANE_SHARE);
    });

    // Same market, timeframe and style as before: keep the view, measured from the
    // latest bar so new bars stay in sight. Otherwise show the most recent history.
    const n = data.bars.length;
    const viewKey = `${data.symbol.code}|${data.timeframe}|${data.style}`;
    const saved = viewRef.current;
    if (n > 0 && focusTime !== undefined) {
      const idx = data.bars.findIndex((b) => b.time >= focusTime);
      const at = idx < 0 ? n - 1 : idx;
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, at - 60), to: Math.min(n + 4, at + 60) });
    } else if (n > 0) {
      if (saved && saved.key === viewKey) {
        chart.timeScale().setVisibleLogicalRange({ from: n - saved.fromEnd, to: n - saved.toEnd });
      } else {
        const from = Math.max(0, n - 160);
        chart.timeScale().setVisibleLogicalRange({ from, to: n + Math.min(8, data.futureTimes.length) });
      }
    }

    // Legend follows the crosshair; otherwise shows the latest bar.
    const byTime = new Map(data.bars.map((b) => [b.time, b]));
    setLegend(data.bars[n - 1] ?? null);
    chart.subscribeCrosshairMove((param) => {
      const t = param.time as number | undefined;
      setLegend((t !== undefined && byTime.get(t)) || data.bars[n - 1] || null);
    });

    syncPlan();

    // Drag the plan's lines up and down. Grabbing within 7 pixels of a line picks it up.
    const el = host.current;
    let dragging: PlanKey | null = null;
    const step = Math.pow(10, -precision);
    const near = (y: number): PlanKey | null => {
      const p = planRef.current;
      if (!p || !onPlanChangeRef.current) return null;
      let best: PlanKey | null = null;
      let bestDist = 7;
      (["stop", "target", "entry"] as PlanKey[]).forEach((key) => {
        const price = key === "target" ? p.target : p[key];
        if (price === null) return;
        const yy = main.priceToCoordinate(price);
        if (yy !== null && Math.abs(yy - y) <= bestDist) {
          best = key;
          bestDist = Math.abs(yy - y);
        }
      });
      return best;
    };
    const localY = (e: PointerEvent) => e.clientY - el.getBoundingClientRect().top;
    const onDown = (e: PointerEvent) => {
      const key = near(localY(e));
      if (!key) return;
      dragging = key;
      chart.applyOptions({ handleScroll: false, handleScale: false });
      chart.priceScale("right").applyOptions({ autoScale: false }); // the scale holds still while you drag
      el.setPointerCapture(e.pointerId);
      e.preventDefault();
      e.stopPropagation();
    };
    const onMove = (e: PointerEvent) => {
      const y = localY(e);
      if (!dragging) {
        el.style.cursor = near(y) ? "ns-resize" : "";
        return;
      }
      const paneHeight = chart.panes()[0]?.getHeight() ?? el.clientHeight;
      const price = main.coordinateToPrice(Math.min(paneHeight - 4, Math.max(4, y))); // can't leave the chart
      const p = planRef.current;
      if (price === null || !p || price <= 0) return;
      const next = { ...p, [dragging]: Number((Math.round(price / step) * step).toFixed(precision)) };
      planRef.current = next;
      onPlanChangeRef.current?.(next); // the lines redraw from the new plan, so they always match the numbers
    };
    const onUp = (e: PointerEvent) => {
      if (!dragging) return;
      dragging = null;
      chart.applyOptions({ handleScroll: true, handleScale: true });
      chart.priceScale("right").applyOptions({ autoScale: true });
      if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
    };
    el.addEventListener("pointerdown", onDown, { capture: true });
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);

    return () => {
      el.removeEventListener("pointerdown", onDown, { capture: true });
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
      el.style.cursor = "";
      mainRef.current = null;
      zonesRef.current = null;
      const range = chart.timeScale().getVisibleLogicalRange();
      if (range && n > 0) viewRef.current = { key: viewKey, fromEnd: n - range.from, toEnd: n - range.to };
      chart.remove();
      chartRef.current = null;
    };
    // syncPlan is stable per data set; plan changes are handled by their own effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, markers, focusTime]);

  const p = data.symbol.precision;
  const change = legend ? legend.close - legend.open : 0;
  return (
    <div className="chart-wrap">
      <div className="legend" aria-live="polite">
        <strong>{data.symbol.code.replace("_", "/")}</strong>
        <span className="muted">{data.symbol.name} · {data.timeframe}</span>
        {legend && (
          <span className="ohlc">
            O <b>{fmt(legend.open, p)}</b> H <b>{fmt(legend.high, p)}</b> L <b>{fmt(legend.low, p)}</b> C{" "}
            <b className={change >= 0 ? "up" : "down"}>{fmt(legend.close, p)}</b>
          </span>
        )}
      </div>
      <div ref={host} className="chart-host" />
    </div>
  );
}
