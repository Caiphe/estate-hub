import { useSyncExternalStore } from "react";

const noSubscription = () => () => {};

/**
 * False during server rendering and the first client render, true once React has
 * hydrated. Forms keep their submit buttons disabled until then, so an early click can
 * never fall back to a native browser submission.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    noSubscription,
    () => true,
    () => false,
  );
}
