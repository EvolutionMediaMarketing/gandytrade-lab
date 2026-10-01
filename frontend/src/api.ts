import type { ActiveIndicator, Catalogue, ChartData } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
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
  chart: (symbol: string, timeframe: string, style: string, indicators: ActiveIndicator[]) =>
    request<ChartData>("/api/chart", {
      method: "POST",
      body: JSON.stringify({ symbol, timeframe, style, limit: 1000, indicators }),
    }),
};
