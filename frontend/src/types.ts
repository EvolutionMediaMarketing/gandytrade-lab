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

// --- Strategies and backtests ---

export interface StrategyParam {
  key: string;
  label: string;
  default: number;
  minimum: number;
  maximum: number;
  step: number;
  help: string;
}

export interface StrategyInfo {
  key: string;
  name: string;
  summary: string;
  rules: string[];
  worksWhen: string;
  failsWhen: string;
  exercise: string;
  params: StrategyParam[];
  benchmark: boolean;
  canShort: boolean;
}

export interface CostSettings {
  spread_pct: number;
  slippage_pct: number;
  commission_gbp: number;
  fx_fee_pct: number;
  stamp_duty_pct: number;
  financing_pct_year: number;
}

export interface StrategiesResponse {
  strategies: StrategyInfo[];
  defaultCosts: Record<string, { cash: CostSettings; cfd: CostSettings }>;
  defaultModes: Record<string, "cash" | "cfd">;
}

export interface Metrics {
  start: number;
  final: number;
  net: number;
  returnPct: number;
  annualPct: number | null;
  years: number;
  trades: number;
  wins: number;
  losses: number;
  winRate: number | null;
  avgWin: number | null;
  avgLoss: number | null;
  profitFactor: number | null;
  maxDrawdownPct: number;
  maxDrawdownGbp: number;
  longestLosingRun: number;
  avgR: number | null;
  costs: number;
  grossNet: number;
  exposurePct: number;
}

export interface TradeRow {
  side: "long" | "short";
  entryTime: number;
  entryPrice: number;
  stop: number;
  exitTime: number;
  exitPrice: number;
  exitReason: string;
  units: number;
  pnl: number;
  gross: number;
  costs: number;
  r: number | null;
  bars: number;
  note: string;
}

export interface BacktestResult {
  id: number;
  symbol: SymbolInfo;
  timeframe: string;
  strategy: { key: string; name: string; params: Record<string, number> };
  startBalance: number;
  from: number;
  to: number;
  candles: number;
  source: string;
  sample: boolean;
  headline: string;
  metrics: Metrics;
  buyHold: Metrics;
  warnings: { level: "stop" | "caution" | "info"; text: string }[];
  assumptions: {
    mode: "cash" | "cfd";
    modeLabel: string;
    direction: string;
    leverageCap: number;
    riskPct: number;
    dailyLossPct: number;
    maxDrawdownPct: number;
    costs: CostSettings;
    currency: string;
    fills: string;
  };
  equity: { time: number; value: number }[];
  buyHoldEquity: { time: number; value: number }[];
  trades: TradeRow[];
}

export interface BacktestSummary {
  id: number;
  createdAt: string;
  symbol: string;
  timeframe: string;
  strategy: string;
  strategyName: string;
  symbolName: string;
  returnPct: number;
  annualPct: number | null;
  trades: number;
  maxDrawdownPct: number;
  buyHoldPct: number;
  years: number;
  sample: boolean;
  mode: string;
}

export interface BacktestRequest {
  symbol: string;
  timeframe: string;
  strategy: string;
  params: Record<string, number>;
  start_balance: number;
  risk_pct: number;
  mode: string;
  direction: string;
  years: number;
  daily_loss_pct: number;
  max_drawdown_pct: number;
  costs: Partial<CostSettings>;
}

export interface PositionSize {
  symbol: SymbolInfo;
  mode: "cash" | "cfd";
  side: "long" | "short";
  units: number;
  riskGbp: number;
  valueGbp: number;
  leverageUsed: number;
  leverageCap: number;
  capped: boolean;
  note: string;
  currency: string;
  perGbp: number;
  rateNote: string;
  perPointGbp: number;
  costGbp: number;
  marginGbp: number | null;
}

// --- Signal assistant ---

export type SignalStatus = "complete" | "forming" | "in_trade" | "none";

export interface SignalSide {
  side: "long" | "short";
  status: SignalStatus;
  checks: { label: string; ok: boolean }[];
  met: number;
  total: number;
  reason: string;
  evidence: { trades: number; winRate: number | null; avgR: number | null; lowSample: boolean };
  plan: null | {
    entry: number; stop: number; units: number; riskGbp: number; valueGbp: number; note: string; stopRule: string; exitRule: string;
  };
}

export interface SignalCard {
  key: string;
  name: string;
  summary: string;
  status: SignalStatus;
  best: SignalSide;
  sides: SignalSide[];
  history: { trades: number; returnPct: number; annualPct: number | null; maxDrawdownPct: number; winRate: number | null; years: number; beatsBuyHold: boolean };
  openTrade?: { side: "long" | "short"; since: number; entry: number; stop: number; exitRule: string };
}

export interface SignalsResponse {
  symbol: SymbolInfo;
  timeframe: string;
  candleClosed: number;
  mode: "cash" | "cfd";
  balance: number;
  riskPct: number;
  sample: boolean;
  years: number;
  buyHold: { returnPct: number; annualPct: number | null };
  strategies: SignalCard[];
}
