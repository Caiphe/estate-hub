import { describe, expect, it } from "vitest";

import { EMAIL_MAX, normalizeEmail, subscribeToNewsletter, validateEmail } from "./newsletter";

describe("normalizeEmail", () => {
  it("trims surrounding whitespace only", () => {
    expect(normalizeEmail("  Reader@Example.com \n")).toBe("Reader@Example.com");
  });
});

describe("validateEmail", () => {
  it.each([
    ["", "Enter your email address."],
    ["reader", "Enter a valid email address, like name@example.com."],
    ["reader@example", "Enter a valid email address, like name@example.com."],
    ["read er@example.com", "Enter a valid email address, like name@example.com."],
    [`${"a".repeat(EMAIL_MAX)}@example.com`, `Use at most ${EMAIL_MAX} characters.`],
  ])("rejects %j", (email, message) => {
    expect(validateEmail(email)).toBe(message);
  });

  it.each(["reader@example.com", "first.last+homes@sub.example.co.za"])("accepts %j", (email) => {
    expect(validateEmail(email)).toBeNull();
  });
});

describe("subscribeToNewsletter (mock)", () => {
  it("says plainly that nothing was saved", async () => {
    const result = await subscribeToNewsletter("reader@example.com", 0);
    expect(result.status).toBe("not-saved");
    expect(result.message).toMatch(/isn't live yet, so your address hasn't been saved/);
  });
});
