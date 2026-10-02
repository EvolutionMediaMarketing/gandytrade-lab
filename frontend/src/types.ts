export interface SymbolInfo {
  code: string;
  name: string;
  asset_class: "forex" | "metal" | "commodity" | "index" | "bond" | "stock" | "etf" | "ukstock";
  provider: "oanda" | "twelvedata" | "alphavantage";
  provider_symbol: string;
  precision: number;
}

export interface TimeframeInfo {
  code: string;
  label: string;
  intraday: boolean;
}

export interface ParamDef {
  key: string;
  label: string;
  default: number;
  minimum: number;
  maximum: number;
  step: number;
}

export interface IndicatorDef {
  type: string;
  name: string;
  pane: string;
  description: string;
  intradayOnly: boolean;
  params: ParamDef[];
}

export interface Catalogue {
  symbols: SymbolInfo[];
  timeframes: TimeframeInfo[];
  styles: string[];
  indicators: IndicatorDef[];
  dataSources: { oanda: boolean; twelvedata: boolean; alphavantage: boolean };
  marketCounts: Record<string, number>;
}

export interface ActiveIndicator {
  id: string;
  type: string;
  params: Record<string, number>;
}

export interface Point {
  time: number;
  value: number;
}

export interface IndicatorLine {
  key: string;
  label: string;
  kind?: "line" | "histogram";
  values: Point[];
}

export interface IndicatorResult {
  id: string;
  type: string;
  pane: string;
  params: Record<string, number>;
  lines: IndicatorLine[];
  levels: number[];
  note: string | null;
  fill?: { upper: string; lower: string; twoTone?: boolean };
}

export interface BarData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ChartData {
  symbol: SymbolInfo;
  timeframe: string;
  style: string;
  source: string;
  sample: boolean;
  stale: boolean;
  warnings: string[];
  bars: BarData[];
  indicators: IndicatorResult[];
  futureTimes: number[];
}
