/** Human wording for a Retry-After delay, rounded up so users never retry too early. */
export function formatWait(seconds: number | null): string {
  if (seconds === null || seconds <= 0) return "a few minutes";
  if (seconds < 60) return seconds === 1 ? "1 second" : `${seconds} seconds`;
  const minutes = Math.ceil(seconds / 60);
  return minutes === 1 ? "1 minute" : `${minutes} minutes`;
}

/** Password length as people count it: Unicode characters, not UTF-16 units. */
export function characterCount(value: string): number {
  return [...value].length;
}
