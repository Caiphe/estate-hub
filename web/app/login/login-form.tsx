"use client";

import { useRef, useState, type FormEvent } from "react";

import {
  AlertCircleIcon,
  CheckCircleIcon,
  EyeIcon,
  EyeOffIcon,
  LockIcon,
  MailIcon,
} from "@/components/landing/icons";
import { TextField } from "@/components/text-field";
import { ApiClient } from "@/lib/api/client";
import { ApiError, NetworkError } from "@/lib/api/errors";
import { formatWait } from "@/lib/format";
import { useHydrated } from "@/lib/use-hydrated";

const INVALID_CREDENTIALS = "Incorrect email or password.";

type FieldErrors = { email?: string; password?: string };

function validate(email: string, password: string): FieldErrors {
  const errors: FieldErrors = {};
  if (!email.trim()) errors.email = "Enter your email address.";
  else if (!/^[^\s@]+@[^\s@]+$/.test(email.trim())) errors.email = "Enter a valid email address.";
  if (!password) errors.password = "Enter your password.";
  return errors;
}

/** One message per failure class; credentials errors never say which field was wrong. */
function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401 || error.status === 422) return INVALID_CREDENTIALS;
    if (error.status === 429) {
      return `Too many login attempts. Try again in ${formatWait(error.retryAfter)}.`;
    }
    if (error.status === 503) return "Logging in is temporarily unavailable. Please try again shortly.";
  }
  if (error instanceof NetworkError) return error.message;
  return "Something went wrong. Please try again.";
}

export function LoginForm({
  redirectTo,
  passwordChanged,
}: {
  /** Already validated server-side: a same-origin workspace path. */
  redirectTo: string;
  passwordChanged: boolean;
}) {
  const [client] = useState(() => new ApiClient());
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const hydrated = useHydrated();
  const alertRef = useRef<HTMLDivElement>(null);
  // Set synchronously, so a second submit in the same tick cannot slip past the disabled button.
  const submitting = useRef(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;
    const errors = validate(email, password);
    setFieldErrors(errors);
    setFormError(null);
    if (errors.email || errors.password) {
      // Focus the first invalid field once its error is rendered, so it is announced with it.
      const invalid = errors.email ? "email" : "password";
      requestAnimationFrame(() => document.getElementById(invalid)?.focus());
      return;
    }

    submitting.current = true;
    // Never leave a typed password on screen while the request runs or after it fails.
    setShowPassword(false);
    setPending(true);
    try {
      await client.login(email.trim(), password);
      // A full navigation so the workspace starts from fresh server state. The guard stays
      // set: the form is never submitted again on this page.
      window.location.replace(redirectTo);
    } catch (error) {
      submitting.current = false;
      setPassword("");
      setFormError(messageFor(error));
      setPending(false);
      requestAnimationFrame(() => alertRef.current?.focus());
    }
  }

  // Panels and the submit button carry transparent borders: forced-colors mode drops
  // backgrounds but draws those borders, so each keeps a visible edge.
  return (
    // method="post" and unnamed inputs: if scripts ever fail to load, a native
    // submission can never put credentials in the URL, history, or server logs.
    <form className="grid gap-6" method="post" noValidate onSubmit={onSubmit} aria-busy={pending}>
      {/* One message slot: the notice gives way to an error, so the form grows by one panel at most. */}
      {passwordChanged && !formError && (
        <div
          className="flex gap-3 rounded-sm border border-transparent bg-brand-subtle p-4 font-semibold text-brand-strong"
          role="status"
        >
          <CheckCircleIcon className="size-6 shrink-0" />
          Your password was changed. Log in with your new password.
        </div>
      )}
      {formError && (
        <div
          className="flex gap-3 rounded-sm border border-danger/40 bg-danger-subtle p-4 font-semibold text-danger"
          role="alert"
          tabIndex={-1}
          ref={alertRef}
        >
          <AlertCircleIcon className="size-6 shrink-0" />
          {formError}
        </div>
      )}
      <TextField
        id="email"
        type="email"
        label="Email address"
        placeholder="you@example.com"
        autoComplete="username"
        appearance="site"
        leadingIcon={<MailIcon className="size-6" />}
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        error={fieldErrors.email}
        required
      />
      <div>
        <TextField
          id="password"
          type={showPassword ? "text" : "password"}
          label="Password"
          placeholder="Enter your password"
          autoComplete="current-password"
          appearance="site"
          leadingIcon={<LockIcon className="size-6" />}
          trailing={
            <button
              type="button"
              className="grid size-11 place-items-center rounded-sm text-fg-muted hover:text-fg"
              aria-label={showPassword ? "Hide password" : "Show password"}
              aria-pressed={showPassword}
              aria-controls="password"
              onClick={() => setShowPassword((shown) => !shown)}
            >
              {showPassword ? <EyeOffIcon className="size-6" /> : <EyeIcon className="size-6" />}
            </button>
          }
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          error={fieldErrors.password}
          required
        />
        <div className="mt-1 flex justify-end">
          <button
            type="button"
            className="min-h-11 text-lg font-semibold text-brand underline-offset-4 hover:text-brand-strong hover:underline"
            aria-expanded={helpOpen}
            aria-controls="account-help"
            onClick={() => setHelpOpen((open) => !open)}
          >
            Forgot your password?
          </button>
        </div>
        {/* No reset workflow exists yet, so this explains who can help instead of linking to one. */}
        <p id="account-help" hidden={!helpOpen} className="mt-2 rounded-sm border border-transparent bg-brand-subtle p-4 text-sm text-fg">
          Password reset by email isn&rsquo;t available yet. Contact your EstateHub administrator
          to regain access to your account.
        </p>
      </div>
      <button
        type="submit"
        className="mt-6 inline-flex min-h-16 w-full items-center justify-center rounded-sm border border-transparent bg-brand-deep px-6 text-xl font-bold text-fg-inverse transition duration-150 ease-standard hover:bg-brand-strong disabled:cursor-progress disabled:opacity-75"
        disabled={pending || !hydrated}
      >
        {pending ? "Logging in…" : "Log in"}
      </button>
      <p className="text-center text-lg text-fg-muted">Need access? Contact your administrator.</p>
    </form>
  );
}
