"use client";

import { type FormEvent, useId, useRef, useState } from "react";

import { VisuallyHidden } from "@/components/visually-hidden";
import { normalizeEmail, subscribeToNewsletter, validateEmail, EMAIL_MAX } from "@/lib/landing/newsletter";
import { useHydrated } from "@/lib/use-hydrated";

import { ArrowRightIcon } from "./icons";

type Status =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "done"; message: string }
  | { kind: "invalid"; message: string }
  | { kind: "failed"; message: string };

/**
 * Email field and arrow button as one control. Submission is disabled until hydration:
 * a native fallback would put the address in a GET URL. One polite live region announces
 * errors and the result; while there is no backend, the result says nothing was saved.
 */
export function NewsletterForm() {
  const hydrated = useHydrated();
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const inputRef = useRef<HTMLInputElement>(null);
  const messageId = useId();

  const submitting = status.kind === "submitting";
  const invalid = status.kind === "invalid";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = normalizeEmail(email);
    const problem = validateEmail(normalized);
    if (problem) {
      setStatus({ kind: "invalid", message: problem });
      inputRef.current?.focus();
      return;
    }
    setEmail(normalized);
    setStatus({ kind: "submitting" });
    try {
      const result = await subscribeToNewsletter(normalized);
      setEmail("");
      setStatus({ kind: "done", message: result.message });
    } catch {
      setStatus({ kind: "failed", message: "Something went wrong. Please try again." });
    }
  }

  const message = status.kind === "done" || status.kind === "invalid" || status.kind === "failed" ? status.message : "";

  return (
    <form noValidate onSubmit={handleSubmit} aria-label="Newsletter sign-up" className="grid gap-2">
      <div className="flex">
        <label htmlFor="newsletter-email" className="sr-only">
          Email address
        </label>
        <input
          ref={inputRef}
          id="newsletter-email"
          name="email"
          type="email"
          inputMode="email"
          autoComplete="email"
          placeholder="Enter your email"
          required
          maxLength={EMAIL_MAX}
          value={email}
          aria-invalid={invalid || undefined}
          aria-describedby={message ? messageId : undefined}
          onChange={(event) => {
            setEmail(event.target.value);
            if (status.kind !== "submitting") setStatus({ kind: "idle" });
          }}
          className="h-11 min-w-0 flex-1 rounded-l-sm border border-r-0 border-surface bg-surface px-4 text-sm text-fg placeholder:text-fg-muted aria-invalid:border-danger"
        />
        <button
          type="submit"
          disabled={!hydrated || submitting}
          aria-busy={submitting || undefined}
          className="inline-grid size-11 shrink-0 place-items-center rounded-r-sm bg-brand text-fg-inverse transition duration-150 ease-standard hover:bg-brand-subtle hover:text-brand-strong motion-safe:active:scale-96 disabled:cursor-not-allowed disabled:bg-fg-muted"
        >
          <ArrowRightIcon />
          <VisuallyHidden>{submitting ? "Subscribing…" : "Subscribe"}</VisuallyHidden>
        </button>
      </div>
      <p
        id={messageId}
        role="status"
        className={`min-h-5 text-sm ${status.kind === "done" ? "text-fg-inverse" : "font-semibold text-accent"}`}
      >
        {message}
      </p>
    </form>
  );
}
