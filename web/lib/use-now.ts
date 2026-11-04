import { useSyncExternalStore } from "react";

const TICK_MS = 30_000;

let current: Date | null = null;

function subscribe(onChange: () => void): () => void {
  const timer = window.setInterval(onChange, TICK_MS);
  return () => window.clearInterval(timer);
}

/** The same Date object for the whole minute, so React only re-renders when it changes. */
function snapshot(): Date {
  const now = Date.now();
  if (!current || Math.floor(current.getTime() / 60_000) !== Math.floor(now / 60_000)) {
    current = new Date(now);
  }
  return current;
}

/**
 * The current time to the minute, or null while server rendering and hydrating. Text that
 * depends on the clock or the browser's time zone therefore never mismatches the server
 * HTML, and a page left open moves from morning to afternoon on its own.
 */
export function useNow(): Date | null {
  return useSyncExternalStore(subscribe, snapshot, () => null);
}
