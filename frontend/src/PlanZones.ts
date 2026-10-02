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

export interface TradePlan {
  entry: number;
  stop: number;
  target: number | null;
}

/**
 * Shades a planned trade on the chart: red between entry and stop-loss (what you'd lose),
 * green between entry and target (what you'd gain), from the latest candle to the right edge.
 */
export class PlanZones implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<SeriesType> | null = null;
  private requestUpdate: (() => void) | null = null;
  private plan: TradePlan | null = null;
  private fromTime: number | null = null;
  private box: { x0: number; entry: number; stop: number; target: number | null } | null = null;
  private readonly view: IPrimitivePaneView;

  constructor() {
    const self = this;
    const renderer: IPrimitivePaneRenderer = {
      draw() {},
      drawBackground(target: any) {
        const b = self.box;
        if (!b) return;
        target.useBitmapCoordinateSpace((scope: any) => {
          const ctx: CanvasRenderingContext2D = scope.context;
          const hr = scope.horizontalPixelRatio;
          const vr = scope.verticalPixelRatio;
          const x0 = Math.max(0, b.x0) * hr;
          const w = scope.bitmapSize.width - x0;
          const rect = (a: number, c: number, colour: string) => {
            ctx.fillStyle = colour;
            ctx.fillRect(x0, Math.min(a, c) * vr, w, Math.abs(c - a) * vr);
          };
          rect(b.entry, b.stop, "rgba(248, 113, 113, 0.16)");
          if (b.target !== null) rect(b.entry, b.target, "rgba(52, 211, 153, 0.14)");
        });
      },
    };
    this.view = { zOrder: (): PrimitivePaneViewZOrder => "bottom", renderer: () => renderer };
  }

  setPlan(plan: TradePlan | null, fromTime: number | null): void {
    this.plan = plan;
    this.fromTime = fromTime;
    this.requestUpdate?.();
  }

  attached(param: SeriesAttachedParameter<Time>): void {
    this.chart = param.chart as IChartApi;
    this.series = param.series as ISeriesApi<SeriesType>;
    this.requestUpdate = param.requestUpdate;
  }

  detached(): void {
    this.chart = this.series = this.requestUpdate = null;
  }

  updateAllViews(): void {
    const { chart, series, plan } = this;
    if (!chart || !series || !plan) {
      this.box = null;
      return;
    }
    const x = this.fromTime === null ? 0 : chart.timeScale().timeToCoordinate(this.fromTime as Time) ?? 0;
    const entry = series.priceToCoordinate(plan.entry);
    const stop = series.priceToCoordinate(plan.stop);
    const target = plan.target === null ? null : series.priceToCoordinate(plan.target);
    this.box = entry === null || stop === null ? null : { x0: x, entry, stop, target: target ?? null };
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [this.view];
  }
}
