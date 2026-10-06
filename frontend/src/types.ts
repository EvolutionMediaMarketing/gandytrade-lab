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
  intradayOnly?: boolean;
  suggestedTimeframe?: string;
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
  keptGoing?: boolean;
  limitHit?: number | null;
  monteCarlo?: MonteCarlo | null;
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
  keep_going?: boolean;
}

export interface Quote {
  symbol: SymbolInfo;
  price: number;
  time: number;
  sample: boolean;
  currency: string;
  dailyAtr: number | null;
  suggestedStopLong: number | null;
  suggestedStopShort: number | null;
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
    entry: number; stop: number; units: number; riskGbp: number; valueGbp: number; note: string; stopRule: string; exitRule: string; target?: number; targetRule?: string;
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
  openTrade?: { side: "long" | "short"; since: number; entry: number; stop: number; exitRule: string; exitPending: boolean };
  note?: string;
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

// --- Paper trading ---

export interface PaperTrade {
  /** Trailing stop distance behind the price (price units), or null when the stop is fixed. */
  trailDistance?: number | null;
  id: number;
  symbol: string;
  timeframe: string;
  side: "long" | "short";
  status: "open" | "closed";
  units: number;
  entryPrice: number;
  entryMid: number;
  entryQuoteTs: number;
  entryTime: string;
  stop: number;
  initialStop: number;
  target: number | null;
  riskGbp: number;
  exitPrice: number | null;
  exitTime: string | null;
  exitReason: string;
  pnl: number | null;
  costs: number | null;
  r: number | null;
  source: string;
  strategy: string;
  autoRunId: number | null;
  trend: string;
  reason: string;
  mood: string;
  notes: string;
  lesson: string;
  ruleFlags: string[];
  ruleScore: number;
  // open trades only
  price?: number | null;
  priceTime?: number | null;
  unrealised?: number;
  valueGbp?: number;
  name?: string;
  precision?: number;
  sample?: boolean;
}

/** A trade as listed on the Journal page: every account, with the account's name. */
export interface JournalTrade extends PaperTrade {
  accountId: number;
  accountName: string;
  accountArchived: boolean;
  strategyName: string;
}

export interface PaperAccount {
  id: number;
  name: string;
  mode: "cash" | "cfd";
  startingBalance: number;
  deposits: number;
  /** Everything paid in (start plus deposits) and the profit on it; deposits are never profit. */
  funded?: number;
  profit?: number;
  /** Monthly top-up (0 = off), the day of the month it's added, and the next date (yyyy-mm-dd). */
  topupAmount?: number;
  topupDay?: number;
  nextTopup?: string | null;
  depositHistory?: { amount: number; kind: "monthly" | "manual"; at: string }[];
  cash: number;
  equity: number;
  returnPct: number;
  buyingPower: number;
  used: number;
  riskPct: number;
  dailyLossPct: number;
  maxDrawdownPct: number;
  peakEquity: number;
  maxOpenRiskPct: number;
  openRisk: number;
  openRiskLimit: number;
  halted: boolean;
  haltReason: string;
  archived: boolean;
  openCount: number;
  autoRunning?: number;
  autoPaused?: number;
  block: string;
  open?: PaperTrade[];
  closed?: PaperTrade[];
}

export interface PaperEvent {
  at: string;
  kind: string;
  price: number | null;
  mid: number | null;
  quoteTs: number | null;
  source: string;
  detail: string;
}

export interface PaperOrder {
  account_id: number;
  symbol: string;
  side: "long" | "short";
  stop: number;
  target: number | null;
  timeframe: string;
  trend: string;
  reason: string;
  mood: string;
  confirmed: boolean;
  /** Trailing stop: how far behind the price it follows (price units). Omit for a fixed stop. */
  trail_distance?: number | null;
}

// --- Target odds ---

export interface OddsRow {
  r: number;
  targetPrice: number;
  targetPct: number;
  stopPct: number;
  neitherPct: number;
  medianSeconds: number | null;
  p25Seconds: number | null;
  p75Seconds: number | null;
  grossR: number;
  netR: number;
  viable: boolean;
  breakEvenPct: number;
}

export interface TargetOdds {
  symbol: SymbolInfo;
  timeframe: string;
  side: "long" | "short";
  starts: number;
  horizonCandles: number;
  horizonSeconds: number;
  years: number;
  sample: boolean;
  stopAtr: number;
  costR: number;
  planR: number | null;
  current: OddsRow | null;
  ladder: OddsRow[];
  best: OddsRow;
  anyViable: boolean;
  largestViable: OddsRow | null;
}

export interface LivePrice {
  bid: number;
  ask: number;
  mid: number;
  time: number;
}

export interface AutoRun {
  /** No new entries from 2 hours before to 2 hours after a high-impact event for this market. */
  eventPause?: boolean;
  id: number;
  accountId: number;
  symbol: string;
  name: string;
  timeframe: string;
  strategy: string;
  strategyName: string;
  params: Record<string, number>;
  direction: "long" | "both";
  status: "running" | "paused" | "stopped";
  createdAt: string;
  lastCheckAt: string | null;
  lastCandle: number;
  message: string;
  backtest: {
    returnPct?: number; annualPct?: number | null; trades?: number; winRate?: number | null; avgR?: number | null;
    profitFactor?: number | null; maxDrawdownPct?: number; years?: number; buyHoldReturnPct?: number; tradesPerYear?: number | null;
  };
  live: { trades: number; open: number; net: number; winRate: number | null; avgR: number | null; costs: number };
  openTradeId: number | null;
}

export interface AutoOptions {
  strategies: { key: string; name: string; summary: string; canShort: boolean; intradayOnly?: boolean; suggestedTimeframe?: string }[];
  timeframes: Record<string, string[]>;
  maxRunning: number;
}

export interface AutoPrefill {
  symbol: string;
  timeframe: string;
  strategy: string;
  params?: Record<string, number>;
  direction?: string;
}

export type ResearchCheck = "profitable" | "enoughTrades" | "drawdown" | "robust" | "recent";

export interface ResearchRow {
  market: string;
  name: string;
  assetClass: string;
  timeframe: string;
  strategy: string;
  strategyName: string;
  direction: "long" | "both";
  years: number;
  returnPct: number;
  annualPct: number | null;
  trades: number;
  tradesPerYear: number | null;
  winRate: number | null;
  avgR: number | null;
  profitFactor: number | null;
  maxDrawdownPct: number;
  costs: number;
  grossNet?: number;
  costShare?: number | null;
  variantReturns: number[];
  recentTrades: number;
  recentNet: number;
  buyHoldReturnPct: number;
  buyHoldDrawdownPct: number;
  beatsBuyHold: boolean;
  smootherThanBuyHold: boolean;
  checks: Record<ResearchCheck, boolean>;
  passed: number;
  score: number;
}

export interface ResearchAcross {
  strategy: string;
  strategyName: string;
  direction: "long" | "both";
  timeframe: string;
  markets: number;
  held: number;
  heldMarkets: { market: string; name: string; returnPct: number; passed: number }[];
  avgAnnualPct: number;
  years?: number;
  avgReturnPct?: number;
  tradesPerYear: number;
}

export interface ResearchJob {
  id: number;
  status: "queued" | "running" | "done";
  automatic: boolean;
  settings: { markets?: string[]; timeframes?: string[]; strategies?: string[] };
  createdAt: string;
  finishedAt: string | null;
  done: number;
  total: number;
  message: string;
  summary?: { shortlist: ResearchRow[]; nearMisses: ResearchRow[]; acrossMarkets: ResearchAcross[]; tested: number };
  rows?: ResearchRow[];
  skipped?: { market: string; timeframe: string; reason: string }[];
}

export interface ResearchOptions {
  basket: { code: string; name: string; assetClass: string }[];
  sectors: { name: string; markets: { code: string; name: string; assetClass: string; provider: string }[]; missing: string[] }[];
  strategies: { key: string; name: string; intradayOnly: boolean }[];
  timeframes: string[];
  defaultTimeframes: string[];
  checks: ResearchCheck[];
  minTrades: number;
  maxDrawdownPct: number;
}

export interface BackupStatus {
  offServer: boolean;
  overdue: boolean;
  lastOk: string | null;
  runs: { at: string; ok: boolean; name: string; size: number; restoreTested: boolean; uploaded: boolean; detail: string }[];
}


export interface PerfStats {
  trades: number; wins: number; losses: number; winRate: number | null; net: number; costs: number;
  avgWin: number | null; avgLoss: number | null; payoff: number | null; expectancy: number | null; avgR: number | null;
  profitFactor: number | null; best: number | null; worst: number | null; longestLosingRun: number; avgHoldHours: number | null;
}

export interface Performance {
  account: { id: number; name: string; mode: string; funded: number; equity: number; returnPct: number; openCount: number; maxDrawdownLimit: number };
  all: PerfStats;
  manual: PerfStats;
  auto: PerfStats;
  maxDrawdownPct: number;
  currentDrawdownPct: number;
  ruleScore: number | null;
  curve: { time: number; value: number }[];
  breakdown: { label: string; symbol: string; trades: number; net: number; winRate: number | null; avgR: number | null; costs: number }[];
  feedback: { level: "stop" | "caution" | "info" | "good"; title: string; text: string }[];
}


export interface AlertStatus {
  botConfigured: boolean;
  chatLinked: boolean;
  chatName: string;
  kinds: string[];
  kindLabels: Record<string, string>;
  recent: { at: string; kind: string; text: string; status: string; error: string }[];
}


export interface ReviewTrade {
  id: number; account: string; symbol: string; side: string; who: string; pnl: number; r: number | null;
  exitReason: string; closed: string; reason: string; lesson: string; flags: string[];
}

export interface ReviewFacts {
  week: string; label: string; closed: number; opened: number; manualClosed: number; autoClosed: number;
  net: number; winRate: number | null; avgR: number | null; costs: number; ruleScore: number | null;
  best: ReviewTrade | null; worst: ReviewTrade | null; broken: ReviewTrade[];
  accounts: { name: string; trades: number; net: number; winRate: number | null; opened: number }[];
  runs: { strategy: string; symbol: string; timeframe: string; account: string; status: string; weekTrades: number; weekNet: number;
          totalTrades: number; liveAvgR: number | null; backtestAvgR: number | null; message: string }[];
  noticed: { level: string; title: string; text: string; account: string }[];
  noLesson: number;
}

export interface WeeklyReview {
  week: string;
  facts: ReviewFacts;
  answers: Record<string, string>;
  focus: string;
  completed: boolean;
  completedAt: string | null;
  previousFocus: { week: string; focus: string } | null;
}

export interface ReviewSummary {
  week: string; label: string; focus: string; stuck: string | null; closed: number | null; net: number | null; ruleScore: number | null;
}


export interface BasketInit {
  markets: string[];
  strategy: string;
  timeframe: string;
  direction?: string;
}

export interface BasketResult {
  strategy: { key: string; name: string; label?: string; params: Record<string, number> };
  timeframe: string; mode: string; direction: string; startBalance: number; maxOpenRiskPct: number; riskPct: number;
  keptGoing: boolean; limitHit: number | null; monteCarlo?: MonteCarlo | null;
  from: number; to: number; years: number;
  markets: { market: string; name: string; basketTrades: number; basketNet: number; basketWinRate: number | null; basketAvgR: number | null;
             aloneReturnPct: number; aloneTrades: number; aloneDrawdownPct: number; holdReturnPct: number }[];
  metrics: BacktestResult["metrics"]; buyHold: BacktestResult["buyHold"]; averageAloneReturnPct: number;
  headline: string; warnings: { level: string; text: string }[]; skipped: Record<string, number>;
  equity: { time: number; value: number }[]; buyHoldEquity: { time: number; value: number }[];
  sample: boolean;
}

export type MonteCarlo =
  | { ok: false; reason: string }
  | {
      ok: true; simulations: number; trades: number; riskPct: number; startBalance: number; drawdownLimitPct: number;
      final: Record<"5" | "25" | "50" | "75" | "95", number>;
      returnPct: Record<"5" | "25" | "50" | "75" | "95", number>;
      worstFall: Record<"50" | "75" | "90" | "95" | "99", number>;
      losingRun: Record<"50" | "95" | "99", number>;
      chanceLoss: number; chanceLimit: number; chanceHalved: number;
      replayFall: number; replayFallRank: number;
      curve: { step: number[]; bands: Record<"5" | "25" | "50" | "75" | "95", number[]>; replay: number[] };
      summary: { level: "info" | "caution" | "stop"; text: string }[];
    };

export interface MarketInfo {
  code: string; name: string; assetClass: string; kind: string; exchange: string;
  note: { text: string; drivers: string[]; wikiTitle: string | null } | null;
  wiki: { title: string; description: string; extract: string; url: string } | { none: string } | { error: string } | null;
  profile: {
    name?: string; sector?: string; industry?: string; exchange?: string; country?: string; currency?: string; description?: string;
    website?: string; marketCap?: number; peRatio?: number; dividendYield?: number; high52?: number; low52?: number; beta?: number;
  } & { none?: string; error?: string } | null;
  canProfile: boolean; canNews: boolean;
  news: { items: { title: string; source: string; time: number; url: string }[] } | { none: string } | { error: string } | null;
  newsAt: number | null;
  allowanceLeft: number;
}

/** Walk-forward check and robustness verdict (backend: app/backtest/walkforward.py). */
export interface WalkForwardCheck { key: string; label: string; status: "pass" | "warn" | "fail"; detail: string }
export interface WalkForwardWindow {
  trainFrom: number; trainTo: number; testFrom: number; testTo: number; picked: string; pickedParams: Record<string, number>;
  tunedReturnPct: number; tunedAnnualPct: number | null; testReturnPct: number; testTrades: number; yoursTestReturnPct: number;
}
export interface WalkForwardSetting {
  label: string; params: Record<string, number>; role: string; returnPct: number; annualPct: number | null;
  profitFactor: number | null; trades: number; maxDrawdownPct: number; avgR: number | null;
}
interface WalkForwardMetrics { final: number; returnPct: number; trades: number; winRate: number | null; avgR: number | null; maxDrawdownPct: number }
export type WalkForward = { warnings: { level: string; text: string }[]; sample: boolean } & (
  | { ok: false; reason: string }
  | {
      ok: true; strategy: { key: string; name: string; params: Record<string, number> }; segments: number; trainSegments: number;
      windows: WalkForwardWindow[]; candidates: string[];
      unseen: { from: number; to: number; metrics: WalkForwardMetrics; annualPct: number | null; equity: { time: number; value: number }[] };
      yours: { metrics: WalkForwardMetrics; annualPct: number | null; equity: { time: number; value: number }[] };
      tunedAnnualPct: number | null; efficiencyPct: number | null; settings: WalkForwardSetting[]; monteCarlo: MonteCarlo;
      checks: WalkForwardCheck[]; verdict: { key: "reject" | "watchlist" | "incubate" | "candidate"; label: string; text: string; passed: number; total: number };
      notes: string[]; headline: string; startBalance: number;
    });

/** A paper order waiting for a price (backend: app/paper/orders.py). */
export interface PriceOrder {
  id: number; accountId: number; symbol: string; timeframe: string; side: "long" | "short";
  kind: "Buy stop" | "Buy limit" | "Sell stop" | "Sell limit" | "Buy at the open" | "Sell at the open"; level: number;
  direction: "up" | "down" | "open";
  stop: number; target: number | null; status: "waiting" | "filled" | "cancelled" | "expired" | "failed";
  placedMid: number; precision: number; createdAt: string | null; expiresAt: string | null; finishedAt: string | null;
  message: string; tradeId: number | null; reason: string; ruleFlags: string[]; trailDistance: number | null;
}

/** 12-week course progress (backend: app/course.py). */
export interface CourseWeek {
  week: number; unlocked: boolean; complete: boolean; startedAt: string | null;
  quizScore: number; quizPassed: boolean; quizPassedAt: string | null;
  task: "auto" | "self" | "plan"; taskDone: boolean; taskDoneAt: string | null; taskDetail: string; note: string;
}
export interface CourseProgress { weeks: CourseWeek[]; completed: number; current: number | null; passMark: number; questions: number }

/** Market replay (backend: app/routes/replay.py). */
export interface ReplayData extends ChartData {
  startIndex: number;
  rates: number[];
  mode: "cash" | "cfd";
  costs: { spread_pct: number; slippage_pct: number; commission_gbp: number; fx_fee_pct: number; stamp_duty_pct: number; financing_pct_year: number };
  leverage: number;
  /** Major news that touched this market in the window: shown once its candle is revealed. */
  events: { date: string; time: number; title: string; text: string }[];
}
export interface ReplaySessionRow {
  id: number; symbol: string; timeframe: string; startTs: number; endTs: number; candles: number; trades: number; wins: number;
  netGbp: number; returnPct: number; buyHoldPct: number; maxDrawdownPct: number; avgR: number | null; lesson: string; createdAt: string;
  /** The trades taken, to look at the replay again (missing on replays saved before this was kept). */
  tradesDetail: ReplayTrade[] | null;
}
export interface ReplayTrade {
  side: 1 | -1; entryTime: number; exitTime: number; entryPrice: number; exitPrice: number; stop: number;
  pnl: number; r: number | null; reason: string;
}

/** Economic calendar (backend: app/market/calendar.py). */
export interface CalendarEvent {
  key: string; title: string; country: string; what: string; time: number; approx: boolean; tentative: boolean;
  inSeconds: number; source: string; affects: boolean;
}
export interface CalendarResponse {
  events: CalendarEvent[];
  soon: CalendarEvent | null;
  coverage: { checked: string; until: Record<string, string>; runningOut: string[] };
}

export interface CalendarSeriesStatus {
  key: string; title: string; until: string | null; source: string; checkedAt: string | null; ok: boolean | null; message: string;
  /** Coming dates added from the publisher's page (on top of the built-in ones). */
  fromPages: string[];
}
export interface CalendarStatus { series: CalendarSeriesStatus[]; coverage: CalendarResponse["coverage"] }
