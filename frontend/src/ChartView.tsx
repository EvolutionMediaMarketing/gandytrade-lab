import { useEffect, useRef, useState } from "react";
import {
  AreaSeries,
  BarSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  IChartApi,
  ISeriesApi,
  LineSeries,
  LineStyle,
  SeriesType,
  Time,
  createChart,
} from "lightweight-charts";
import { BandFill } from "./BandFill";
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

export default function ChartView({ data }: { data: ChartData }) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
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
      timeScale: { borderColor: C.grid, timeVisible: data.timeframe.endsWith("m") || data.timeframe.endsWith("h"), rightOffset: 4 },
      localization: { locale: "en-GB" },
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

    // Show the most recent part of the history by default.
    const n = data.bars.length;
    if (n > 0) {
      const from = Math.max(0, n - 160);
      chart.timeScale().setVisibleLogicalRange({ from, to: n + Math.min(8, data.futureTimes.length) });
    }

    // Legend follows the crosshair; otherwise shows the latest bar.
    const byTime = new Map(data.bars.map((b) => [b.time, b]));
    setLegend(data.bars[n - 1] ?? null);
    chart.subscribeCrosshairMove((param) => {
      const t = param.time as number | undefined;
      setLegend((t !== undefined && byTime.get(t)) || data.bars[n - 1] || null);
    });

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [data]);

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
