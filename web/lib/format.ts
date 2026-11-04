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

/** Up to two initials for an avatar: first and last word, so "Ada M. Lovelace" is "AL". */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  const first = [...words[0]][0];
  const last = words.length > 1 ? [...words[words.length - 1]][0] : "";
  return `${first}${last}`.toLocaleUpperCase();
}

export type Greeting = "Good morning" | "Good afternoon" | "Good evening";

/** Morning from 05:00, afternoon from 12:00, evening from 18:00 until 05:00. */
export function greetingFor(date: Date, timeZone?: string): Greeting {
  const hour = Number(
    new Intl.DateTimeFormat("en-US", { hour: "numeric", hourCycle: "h23", timeZone }).format(date),
  );
  if (hour >= 5 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 18) return "Good afternoon";
  return "Good evening";
}

/** A day as people read it, such as "Wed, 04 Nov 2026" in en-GB, in their own locale. */
export function formatDay(date: Date, options: { locale?: string; timeZone?: string } = {}): string {
  return new Intl.DateTimeFormat(options.locale, {
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: options.timeZone,
  }).format(date);
}

/**
 * The calendar day as YYYY-MM-DD for a `<time dateTime>`, in the same time zone as the
 * visible text. Not toISOString(), which gives the UTC day and is wrong near midnight.
 */
export function isoDay(date: Date, timeZone?: string): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone,
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

/** A name to address someone by: whitespace collapsed, never empty. */
export function displayName(fullName: string): string {
  return fullName.trim().replace(/\s+/g, " ") || "there";
}

/** A moment as people read it, such as "4 Nov 2026, 17:05" in en-GB, in their own locale. */
export function formatDateTime(iso: string, options: { locale?: string; timeZone?: string } = {}): string {
  return new Intl.DateTimeFormat(options.locale, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: options.timeZone,
  }).format(new Date(iso));
}
