"use client";

import { useRef, useState, type FormEvent } from "react";

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
      return `Too many sign-in attempts. Try again in ${formatWait(error.retryAfter)}.`;
    }
    if (error.status === 503) return "Sign-in is temporarily unavailable. Please try again shortly.";
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
  const hydrated = useHydrated();
  const alertRef = useRef<HTMLDivElement>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const errors = validate(email, password);
    setFieldErrors(errors);
    setFormError(null);
    if (errors.email || errors.password) return;

    setPending(true);
    try {
      await client.login(email.trim(), password);
      // A full navigation so the workspace starts from fresh server state.
      window.location.replace(redirectTo);
    } catch (error) {
      setPassword("");
      setFormError(messageFor(error));
      setPending(false);
      requestAnimationFrame(() => alertRef.current?.focus());
    }
  }

  return (
    // method="post" and unnamed inputs: if scripts ever fail to load, a native
    // submission can never put credentials in the URL, history, or server logs.
    <form className="form" method="post" noValidate onSubmit={onSubmit} aria-busy={pending}>
      {passwordChanged && !formError && (
        <div className="notice" role="status">
          Your password was changed. Sign in with your new password.
        </div>
      )}
      {formError && (
        <div className="form-error" role="alert" tabIndex={-1} ref={alertRef}>
          {formError}
        </div>
      )}
      <TextField
        id="email"
        type="email"
        label="Email"
        autoComplete="username"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        error={fieldErrors.email}
        required
      />
      <TextField
        id="password"
        type="password"
        label="Password"
        autoComplete="current-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        error={fieldErrors.password}
        required
      />
      <button type="submit" className="button" disabled={pending || !hydrated}>
        {pending ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
