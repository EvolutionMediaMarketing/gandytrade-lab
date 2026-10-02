import type {
  ActiveIndicator, BacktestRequest, BacktestResult, BacktestSummary, Catalogue, ChartData, PaperAccount, PaperEvent, PaperOrder, PaperTrade, PositionSize, Quote, SignalsResponse, StrategiesResponse, SymbolInfo,
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
    const detail = typeof data?.detail === "string" ? data.detail : `Request failed (${res.status}).`;
    throw new ApiError(res.status, detail);
  }
  return data as T;
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
  changePaperAccount: (id: number, body: { name?: string; risk_pct?: number; archived?: boolean; resume?: boolean }) =>
    request<PaperAccount>(`/api/paper/accounts/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  placePaperTrade: (body: PaperOrder) =>
    request<{ trade: PaperTrade; note: string }>("/api/paper/orders", { method: "POST", body: JSON.stringify(body) }),
  changePaperTrade: (id: number, body: { stop?: number; target?: number; clear_target?: boolean; notes?: string; lesson?: string; mood?: string }) =>
    request<{ trade: PaperTrade }>(`/api/paper/trades/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  closePaperTrade: (id: number) => request<{ trade: PaperTrade }>(`/api/paper/trades/${id}/close`, { method: "POST" }),
  paperEvents: (id: number) => request<{ events: PaperEvent[] }>(`/api/paper/trades/${id}/events`),
  quote: (symbol: string) => request<Quote>(`/api/tools/quote?${new URLSearchParams({ symbol })}`),
  positionSize: (body: { symbol: string; balance: number; risk_pct: number; entry: number; stop: number; mode: string }) =>
    request<PositionSize>("/api/tools/position-size", { method: "POST", body: JSON.stringify(body) }),
  deleteBacktest: (id: number) => request<{ ok: boolean }>(`/api/backtests/${id}`, { method: "DELETE" }),
};
