"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError } from "./api/errors";

export type Remote<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "forbidden" }
  | { status: "not_found" }
  | { status: "error" };

type Settled<T> = { key: string; value: Exclude<Remote<T>, { status: "loading" }> };

/**
 * Load data for `key` and reload it on demand. A new key, a reload, or unmounting aborts
 * the request in flight through `signal`, and results for an older key are ignored, so fast
 * filter changes never show stale data. 403 and 404 become states the page renders.
 */
export function useRemote<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
): [Remote<T>, () => void] {
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let current = true;
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => current && setSettled({ key, value: { status: "ready", data } }),
      (error: unknown) => {
        if (!current) return;
        const status =
          error instanceof ApiError && error.status === 403
            ? "forbidden"
            : error instanceof ApiError && (error.status === 404 || error.status === 422)
              ? "not_found"
              : "error";
        setSettled({ key, value: { status } });
      },
    );
    return () => {
      current = false;
      controller.abort();
    };
    // `load` is rebuilt every render; `key` and `version` decide when to fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, version]);

  const reload = useCallback(() => setVersion((value) => value + 1), []);
  const state: Remote<T> =
    settled && settled.key === `${key}` ? settled.value : { status: "loading" };
  return [state, reload];
}
