import { useEffect, useState } from "react";
import { api } from "./api";
import type { LivePrice } from "./types";

const POLL_MS = 2000;

/** The latest streamed price for each market (OANDA markets only), checked every 2 seconds while the page is visible. */
export function useLivePrices(symbols: string[], enabled = true): { prices: Record<string, LivePrice>; live: boolean } {
  const [prices, setPrices] = useState<Record<string, LivePrice>>({});
  const [live, setLive] = useState(false);
  const key = symbols.slice().sort().join(",");

  useEffect(() => {
    setPrices({});
    setLive(false);
    if (!enabled || !key) return;
    let stopped = false;
    const tick = () => {
      if (document.visibilityState !== "visible") return;
      api.live(key.split(",")).then((r) => {
        if (stopped) return;
        setPrices(r.prices);
        setLive(r.live);
      }).catch(() => setLive(false));
    };
    tick();
    const timer = window.setInterval(tick, POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [key, enabled]);

  return { prices, live };
}
