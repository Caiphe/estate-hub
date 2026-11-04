import { useSyncExternalStore } from "react";

let revision = 0;
const listeners = new Set<() => void>();

/**
 * Record that staff data changed in this tab. Every successful staff mutation calls this
 * (see staffApi), so views keyed on the revision fetch again instead of showing stale counts.
 */
export function notifyStaffChanged(): void {
  revision += 1;
  for (const listener of listeners) listener();
}

export function staffRevision(): number {
  return revision;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The current staff revision; changes after every successful staff mutation in this tab. */
export function useStaffRevision(): number {
  return useSyncExternalStore(subscribe, staffRevision, () => 0);
}
