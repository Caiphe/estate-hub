"use client";

import { useRef, useState, type FormEvent } from "react";

import { TextField } from "@/components/text-field";
import { ApiError, NetworkError } from "@/lib/api/errors";
import { characterCount, formatWait } from "@/lib/format";
import { useHydrated } from "@/lib/use-hydrated";
import { useSession } from "@/lib/session";

const MIN_LENGTH = 12;
const MAX_LENGTH = 128;

type Field = "current" | "new" | "confirmation";
type FieldErrors = Partial<Record<Field, string>>;

const API_FIELDS: Record<string, Field> = {
  current_password: "current",
  new_password: "new",
  new_password_confirmation: "confirmation",
};

function validate(current: string, next: string, confirmation: string): FieldErrors {
  const errors: FieldErrors = {};
  if (!current) errors.current = "Enter your current password.";
  const length = characterCount(next);
  if (length < MIN_LENGTH) errors.new = `Use at least ${MIN_LENGTH} characters.`;
  else if (length > MAX_LENGTH) errors.new = `Use at most ${MAX_LENGTH} characters.`;
  else if (next === current) errors.new = "Choose a password different from your current one.";
  if (confirmation !== next) errors.confirmation = "The passwords do not match.";
  return errors;
}

export default function ChangePasswordPage() {
  const { client } = useSession();
  const [values, setValues] = useState<Record<Field, string>>({
    current: "",
    new: "",
    confirmation: "",
  });
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const hydrated = useHydrated();
  const alertRef = useRef<HTMLDivElement>(null);

  const update = (field: Field) => (event: { target: { value: string } }) =>
    setValues((previous) => ({ ...previous, [field]: event.target.value }));

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = validate(values.current, values.new, values.confirmation);
    setErrors(found);
    setFormError(null);
    if (Object.keys(found).length) return;

    setPending(true);
    try {
      await client.changePassword({
        currentPassword: values.current,
        newPassword: values.new,
        confirmation: values.confirmation,
      });
      // Every session was revoked by the API; sign in again with the new password.
      window.location.replace("/login?changed=1");
    } catch (error) {
      setPending(false);
      if (error instanceof ApiError && error.status === 422) {
        const mapped: FieldErrors = {};
        for (const [name, messages] of Object.entries(error.fields)) {
          const field = API_FIELDS[name];
          if (field && messages[0]) mapped[field] = messages[0].replace(/^Value error, /, "");
        }
        setErrors(mapped);
        if (Object.keys(mapped).length) return;
      }
      setFormError(
        error instanceof ApiError && error.status === 429
          ? `Too many attempts. Try again in ${formatWait(error.retryAfter)}.`
          : error instanceof NetworkError
            ? error.message
            : "Your password could not be changed. Please try again.",
      );
      requestAnimationFrame(() => alertRef.current?.focus());
    }
  }

  return (
    <section className="panel" aria-labelledby="password-heading">
      <h1 id="password-heading" className="page-title">
        Change password
      </h1>
      <p className="summary">You will be signed out everywhere and asked to sign in again.</p>
      {/* method="post" with unnamed inputs: a native submission can never leak values. */}
      <form className="form" method="post" noValidate onSubmit={onSubmit} aria-busy={pending}>
        {formError && (
          <div className="form-error" role="alert" tabIndex={-1} ref={alertRef}>
            {formError}
          </div>
        )}
        <TextField
          id="current-password"
          type="password"
          label="Current password"
          autoComplete="current-password"
          value={values.current}
          onChange={update("current")}
          error={errors.current}
          required
        />
        <TextField
          id="new-password"
          type="password"
          label="New password"
          hint={`${MIN_LENGTH} to ${MAX_LENGTH} characters. Spaces and passphrases are welcome.`}
          autoComplete="new-password"
          value={values.new}
          onChange={update("new")}
          error={errors.new}
          required
        />
        <TextField
          id="confirm-password"
          type="password"
          label="Confirm new password"
          autoComplete="new-password"
          value={values.confirmation}
          onChange={update("confirmation")}
          error={errors.confirmation}
          required
        />
        <button type="submit" className="button" disabled={pending || !hydrated}>
          {pending ? "Changing password…" : "Change password"}
        </button>
      </form>
    </section>
  );
}
