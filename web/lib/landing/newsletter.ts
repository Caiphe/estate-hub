/**
 * Newsletter sign-up. There is no mailing-list backend yet, so `subscribeToNewsletter` is
 * a mock: it never stores, sends, or logs the address, and its result tells the visitor
 * plainly that nothing was saved. Replace it with a real API call when one exists.
 */

import { characterCount } from "@/lib/format";

/** RFC 5321 caps a forward path at 254 characters. */
export const EMAIL_MAX = 254;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function normalizeEmail(value: string): string {
  return value.trim();
}

/** Error message for an already-normalized address, or null when it is acceptable. */
export function validateEmail(email: string): string | null {
  if (!email) return "Enter your email address.";
  if (characterCount(email) > EMAIL_MAX) return `Use at most ${EMAIL_MAX} characters.`;
  if (!EMAIL_PATTERN.test(email)) return "Enter a valid email address, like name@example.com.";
  return null;
}

export type SubscribeResult = { status: "not-saved"; message: string };

/** Mock handler: resolves after a short pause and keeps nothing. */
export async function subscribeToNewsletter(email: string, delayMs = 600): Promise<SubscribeResult> {
  void email; // Deliberately unused: no storage, network, or logging.
  await new Promise((resolve) => setTimeout(resolve, delayMs));
  return {
    status: "not-saved",
    message:
      "Thanks for your interest. Newsletter sign-up isn't live yet, so your address hasn't been saved. Please check back soon.",
  };
}
