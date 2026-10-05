import { useEffect, useRef } from "react";
import { ColorType, LineSeries, Time, TickMarkType, createChart } from "lightweight-charts";

interface Point {
  time: number;
  value: number;
}

const gbp = (v: number) => `£${v.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function tick(seconds: number, type: TickMarkType): string {
  const d = new Date(seconds * 1000);
  if (type === TickMarkType.Year) return d.toLocaleDateString("en-GB", { year: "numeric" });
  if (type === TickMarkType.Month) return d.toLocaleDateString("en-GB", { month: "short" });
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/** The account balance over time: the strategy against simply buying and holding. */
export default function EquityChart({ strategy, buyHold = [], start, label = "Strategy" }: { strategy: Point[]; buyHold?: Point[]; start: number; label?: string }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!host.current) return;
    const chart = createChart(host.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#0d131a" }, textColor: "#9fb0c0", fontFamily: "'IBM Plex Sans', system-ui, sans-serif" },
      grid: { vertLines: { color: "#1a242f" }, horzLines: { color: "#1a242f" } },
      rightPriceScale: { borderColor: "#1a242f" },
      timeScale: { borderColor: "#1a242f", tickMarkFormatter: (t: Time, type: TickMarkType) => tick(t as number, type) },
      localization: {
        locale: "en-GB",
        priceFormatter: gbp,
        timeFormatter: (t: Time) => new Date((t as number) * 1000).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }),
      },
    });
    if (buyHold.length) {
      const bh = chart.addSeries(LineSeries, { color: "#8a9bad", lineWidth: 1, priceLineVisible: false, title: "Buy and hold" });
      bh.setData(buyHold.map((p) => ({ time: p.time as Time, value: p.value })));
    }
    const st = chart.addSeries(LineSeries, { color: "#34d399", lineWidth: 2, priceLineVisible: false, title: label });
    st.setData(strategy.map((p) => ({ time: p.time as Time, value: p.value })));
    st.createPriceLine({ price: start, color: "#3b4b5c", lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "Start" });
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [strategy, buyHold, start, label]);

  return <div ref={host} className="equity-host" role="img" aria-label="Account balance over time, strategy versus buy and hold" />;
}
