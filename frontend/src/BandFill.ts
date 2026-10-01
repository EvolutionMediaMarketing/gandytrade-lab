import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  PrimitivePaneViewZOrder,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from "lightweight-charts";
import type { Point } from "./types";

interface Segment {
  x0: number;
  x1: number;
  u0: number;
  u1: number;
  l0: number;
  l1: number;
  up: boolean;
}

/**
 * Shades the area between two lines: the Ichimoku cloud (green when span A is
 * above span B, red when below) or the inside of Bollinger Bands.
 */
export class BandFill implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<SeriesType> | null = null;
  private segments: Segment[] = [];
  private readonly pairs: { time: number; upper: number; lower: number }[];
  private readonly view: IPrimitivePaneView;

  constructor(
    upper: Point[],
    lower: Point[],
    private readonly colours: { up: string; down: string },
    private readonly twoTone: boolean,
  ) {
    const lowerByTime = new Map(lower.map((p) => [p.time, p.value]));
    this.pairs = upper
      .filter((p) => lowerByTime.has(p.time))
      .map((p) => ({ time: p.time, upper: p.value, lower: lowerByTime.get(p.time)! }));

    const self = this;
    const renderer: IPrimitivePaneRenderer = {
      draw() {},
      drawBackground(target: any) {
        target.useBitmapCoordinateSpace((scope: any) => {
          const ctx: CanvasRenderingContext2D = scope.context;
          const hr = scope.horizontalPixelRatio;
          const vr = scope.verticalPixelRatio;
          for (const s of self.segments) {
            ctx.fillStyle = !self.twoTone || s.up ? self.colours.up : self.colours.down;
            ctx.beginPath();
            ctx.moveTo(s.x0 * hr, s.u0 * vr);
            ctx.lineTo(s.x1 * hr, s.u1 * vr);
            ctx.lineTo(s.x1 * hr, s.l1 * vr);
            ctx.lineTo(s.x0 * hr, s.l0 * vr);
            ctx.closePath();
            ctx.fill();
          }
        });
      },
    };
    this.view = {
      zOrder: (): PrimitivePaneViewZOrder => "bottom",
      renderer: () => renderer,
    };
  }

  attached(param: SeriesAttachedParameter<Time>): void {
    this.chart = param.chart as IChartApi;
    this.series = param.series as ISeriesApi<SeriesType>;
  }

  detached(): void {
    this.chart = null;
    this.series = null;
  }

  updateAllViews(): void {
    const chart = this.chart;
    const series = this.series;
    if (!chart || !series) return;
    const ts = chart.timeScale();
    const pts: { x: number; u: number; l: number; up: boolean }[] = [];
    for (const p of this.pairs) {
      const x = ts.timeToCoordinate(p.time as Time);
      const u = series.priceToCoordinate(p.upper);
      const l = series.priceToCoordinate(p.lower);
      if (x === null || u === null || l === null) continue;
      pts.push({ x, u, l, up: p.upper >= p.lower });
    }
    const segs: Segment[] = [];
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1];
      const b = pts[i];
      segs.push({ x0: a.x, x1: b.x, u0: a.u, u1: b.u, l0: a.l, l1: b.l, up: a.up && b.up ? true : !a.up && !b.up ? false : b.up });
    }
    this.segments = segs;
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [this.view];
  }
}
