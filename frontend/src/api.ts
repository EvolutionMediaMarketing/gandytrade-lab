import type {
  ActiveIndicator, AlertStatus, BasketResult, ReviewSummary, WeeklyReview, AutoOptions, Performance, BackupStatus, AutoRun, ResearchJob, ResearchOptions, BacktestRequest, BacktestResult, BacktestSummary, Catalogue, ChartData, PaperAccount, PaperEvent, PaperOrder, PaperTrade, LivePrice, PositionSize, Quote, SignalsResponse, TargetOdds, StrategiesResponse, SymbolInfo, MarketInfo, WalkForward, PriceOrder,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// Background requests (automatic refreshes) don't count as you being active, so an
// unattended tab still signs out after the idle timeout.
async function request<T>(path: string, init: RequestInit = {}, background = false): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (background) headers["X-GT-Background"] = "1";
  if (init.body) headers["Content-Type"] = "application/json";
  if (init.method && init.method !== "GET") headers["X-Requested-With"] = "gandytrade";
  const res = await fetch(path, { credentials: "same-origin", ...init, headers });
  let data: any = null;
  try {
    data = await res.json();
  } catch {
    /* empty body */
  }
  if (!res.ok) {
    let detail = typeof data?.detail === "string" ? data.detail : `Request failed (${res.status}).`;
    if (Array.isArray(data?.detail) && data.detail.length) {
      // FastAPI validation errors: name the field in plain words.
      const first = data.detail[0];
      const field = String(first?.loc?.[first.loc.length - 1] ?? "value").replace(/_/g, " ");
      detail = `Please check the ${field}: ${String(first?.msg ?? "it isn't valid").replace(/^Input should be /, "it should be ")}.`;
    }
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export interface BasketRequest {
  markets: string[]; timeframe: string; strategy: string; params: Record<string, number>; direction: string; start_balance: number;
  risk_pct: number; max_open_risk_pct: number; years: number; mode: string; keep_going: boolean;
}

export const api = {
  me: () => request<{ username: string }>("/api/auth/me"),
  login: (username: string, password: string, code: string) =>
    request<{ username: string }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password, code }),
    }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  catalogue: () => request<Catalogue>("/api/catalogue"),
  favourites: () => request<{ favourites: SymbolInfo[] }>("/api/favourites"),
  setFavourite: (code: string, on: boolean) =>
    request<{ favourites: SymbolInfo[] }>(`/api/favourites/${encodeURIComponent(code)}`, { method: on ? "PUT" : "DELETE" }),
  marketInfo: (symbol: string, full: boolean, signal?: AbortSignal) =>
    request<MarketInfo>(`/api/markets/info?${new URLSearchParams({ symbol, full: full ? "true" : "false" })}`, { signal }, true),
  marketNews: (symbol: string) =>
    request<{ news: MarketInfo["news"]; newsAt: number; allowanceLeft: number }>(
      `/api/markets/info/news?${new URLSearchParams({ symbol })}`, { method: "POST" }),
  searchMarkets: (q: string, assetClass: string, signal?: AbortSignal) =>
    request<{ results: SymbolInfo[] }>(
      `/api/markets/search?${new URLSearchParams({ q, class: assetClass, limit: "60" })}`,
      { signal },
    ),
  chart: (symbol: string, timeframe: string, style: string, indicators: ActiveIndicator[], background = false, limit = 1000) =>
    request<ChartData>(
      "/api/chart",
      { method: "POST", body: JSON.stringify({ symbol, timeframe, style, limit, indicators }) },
      background,
    ),
  signals: (symbol: string, timeframe: string, balance: number, risk: number, background = false) =>
    request<SignalsResponse>(
      `/api/signals?${new URLSearchParams({ symbol, timeframe, balance: String(balance), risk: String(risk) })}`, {}, background,
    ),
  strategies: () => request<StrategiesResponse>("/api/strategies"),
  runBacktest: (body: BacktestRequest) =>
    request<BacktestResult>("/api/backtests", { method: "POST", body: JSON.stringify(body) }),
  backtests: () => request<{ runs: BacktestSummary[] }>("/api/backtests"),
  backtest: (id: number) => request<BacktestResult>(`/api/backtests/${id}`),
  paperAccounts: () => request<{ accounts: PaperAccount[] }>("/api/paper/accounts"),
  paperAccount: (id: number, background = false) => request<PaperAccount>(`/api/paper/accounts/${id}`, {}, background),
  newPaperAccount: (body: { name: string; starting_balance: number; mode: string; risk_pct: number }) =>
    request<PaperAccount>("/api/paper/accounts", { method: "POST", body: JSON.stringify(body) }),
  changePaperAccount: (id: number, body: {
    name?: string; risk_pct?: number; max_open_risk_pct?: number; daily_loss_pct?: number; max_drawdown_pct?: number;
    archived?: boolean; resume?: boolean;
  }) =>
    request<PaperAccount>(`/api/paper/accounts/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deletePaperAccount: (id: number, confirmName: string) =>
    request<{ ok: boolean; trades: number; runs: number }>(`/api/paper/accounts/${id}/delete`, {
      method: "POST", body: JSON.stringify({ confirm_name: confirmName }),
    }),
  placePaperTrade: (body: PaperOrder) =>
    request<{ trade: PaperTrade; note: string }>("/api/paper/orders", { method: "POST", body: JSON.stringify(body) }),
  priceOrders: (q: { account_id?: number; symbol?: string; done?: boolean }) =>
    request<{ waiting: PriceOrder[]; finished: PriceOrder[] }>(`/api/paper/price-orders?${new URLSearchParams(
      Object.entries(q).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]))}`),
  placePriceOrder: (body: Omit<PaperOrder, "side"> & { side: "long" | "short"; level: number; expiry: string }) =>
    request<PriceOrder>("/api/paper/price-orders", { method: "POST", body: JSON.stringify(body) }),
  cancelPriceOrder: (id: number) => request<PriceOrder>(`/api/paper/price-orders/${id}/cancel`, { method: "POST" }),
  changePaperTrade: (id: number, body: { stop?: number; target?: number; clear_target?: boolean; notes?: string; lesson?: string; mood?: string }) =>
    request<{ trade: PaperTrade }>(`/api/paper/trades/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  closePaperTrade: (id: number) => request<{ trade: PaperTrade }>(`/api/paper/trades/${id}/close`, { method: "POST" }),
  paperEvents: (id: number) => request<{ events: PaperEvent[] }>(`/api/paper/trades/${id}/events`),
  targetOdds: (body: { symbol: string; timeframe: string; entry: number; stop: number; target: number | null; mode: string }) =>
    request<TargetOdds>("/api/tools/target-odds", { method: "POST", body: JSON.stringify(body) }),
  live: (symbols: string[]) =>
    request<{ live: boolean; status: string; prices: Record<string, LivePrice> }>(
      `/api/live?${new URLSearchParams({ symbols: symbols.join(",") })}`, {}, true,
    ),
  quote: (symbol: string) => request<Quote>(`/api/tools/quote?${new URLSearchParams({ symbol })}`),
  positionSize: (body: { symbol: string; balance: number; risk_pct: number; entry: number; stop: number; mode: string }) =>
    request<PositionSize>("/api/tools/position-size", { method: "POST", body: JSON.stringify(body) }),
  autoOptions: () => request<AutoOptions>("/api/paper/auto/options"),
  autoRuns: (accountId: number, background = false) =>
    request<{ runs: AutoRun[] }>(`/api/paper/auto?${new URLSearchParams({ account_id: String(accountId) })}`, {}, background),
  startAutoRun: (body: { account_id: number; symbol: string; timeframe: string; strategy: string; direction: string; params?: Record<string, number> }) =>
    request<AutoRun>("/api/paper/auto", { method: "POST", body: JSON.stringify(body) }),
  startBasketRuns: (body: { account_id: number | null; new_account_name?: string; new_account_risk_pct?: number; markets: string[]; timeframe: string; strategy: string; direction: string;
    params: Record<string, number>; stop_run_ids: number[] }) =>
    request<{ runs: AutoRun[] }>("/api/paper/auto/basket", { method: "POST", body: JSON.stringify(body) }),
  changeAutoRun: (id: number, action: "pause" | "resume" | "stop", closeOpen = false) =>
    request<AutoRun>(`/api/paper/auto/${id}`, { method: "POST", body: JSON.stringify({ action, close_open: closeOpen }) }),
  researchOptions: () => request<ResearchOptions>("/api/research/options"),
  researchJobs: (background = false) => request<{ jobs: ResearchJob[] }>("/api/research", {}, background),
  researchJob: (id: number, background = false) => request<ResearchJob>(`/api/research/${id}`, {}, background),
  startResearch: (body: { markets: string[]; timeframes: string[]; strategies: string[] }) =>
    request<ResearchJob>("/api/research", { method: "POST", body: JSON.stringify(body) }),
  backupStatus: (background = false) => request<BackupStatus>("/api/backup/status", {}, background),
  performance: (accountId: number) => request<Performance>(`/api/paper/accounts/${accountId}/performance`),
  coachExport: (accountId: number) => request<{ text: string }>(`/api/paper/accounts/${accountId}/coach-export`),
  alertStatus: () => request<AlertStatus>("/api/alerts"),
  findChats: () => request<{ chats: { chatId: string; name: string; type: string }[] }>("/api/alerts/find-chats", { method: "POST" }),
  linkChat: (chatId: string) => request<AlertStatus>("/api/alerts/link", { method: "POST", body: JSON.stringify({ chat_id: chatId }) }),
  unlinkChat: () => request<AlertStatus>("/api/alerts/unlink", { method: "POST" }),
  chooseAlerts: (kinds: string[]) => request<AlertStatus>("/api/alerts", { method: "PATCH", body: JSON.stringify({ kinds }) }),
  testAlert: () => request<{ ok: boolean }>("/api/alerts/test", { method: "POST" }),
  currentReview: () => request<WeeklyReview>("/api/reviews/current"),
  reviewHistory: () => request<{ reviews: ReviewSummary[] }>("/api/reviews"),
  saveReview: (week: string, body: { answers: Record<string, string>; focus: string; complete: boolean }) =>
    request<WeeklyReview>(`/api/reviews/${week}`, { method: "PUT", body: JSON.stringify(body) }),
  reviewCoach: (week: string) => request<{ text: string }>(`/api/reviews/${week}/coach`),
  runBasket: (body: BasketRequest) =>
    request<BasketResult>("/api/backtests/basket", { method: "POST", body: JSON.stringify(body) }),
  walkForward: (body: BacktestRequest) =>
    request<WalkForward>("/api/backtests/walkforward", { method: "POST", body: JSON.stringify(body) }),
  walkForwardBasket: (body: BasketRequest) =>
    request<WalkForward>("/api/backtests/basket/walkforward", { method: "POST", body: JSON.stringify(body) }),
  deleteBacktest: (id: number) => request<{ ok: boolean }>(`/api/backtests/${id}`, { method: "DELETE" }),
};
