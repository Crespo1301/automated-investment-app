"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// 30s is the operator-friendly default: each refresh re-runs every server
// component (~6 fetches per route), so going faster hammers the FastAPI
// process and ultimately Alpaca. Pause refreshing while the tab is hidden so
// background tabs don't keep churning quota.
export function AutoRefresh({ intervalMs = 30000 }: { intervalMs?: number }) {
  const router = useRouter();

  useEffect(() => {
    let timer: number | undefined;

    const start = () => {
      if (timer !== undefined) return;
      timer = window.setInterval(() => {
        router.refresh();
      }, intervalMs);
    };

    const stop = () => {
      if (timer === undefined) return;
      window.clearInterval(timer);
      timer = undefined;
    };

    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        router.refresh();
        start();
      } else {
        stop();
      }
    };

    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      stop();
    };
  }, [intervalMs, router]);

  return null;
}
