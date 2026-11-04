import type { InputHTMLAttributes, ReactNode } from "react";

type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> & {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  /** Decorative icon inside the input's leading edge; the caller's icon hides itself. */
  leadingIcon?: ReactNode;
  /** A control inside the input's trailing edge, such as a show-password toggle. */
  trailing?: ReactNode;
  /** "workspace" keeps the staff workspace stylesheet; "site" uses the public-site tokens. */
  appearance?: "workspace" | "site";
};

const SITE = {
  field: "grid gap-2",
  label: "text-lg font-bold text-fg",
  hint: "text-sm text-fg-muted",
  input:
    "h-14 w-full rounded-sm border border-line-strong bg-surface px-4 text-lg text-fg placeholder:text-fg-muted aria-invalid:border-2 aria-invalid:border-danger",
  error: "text-sm font-semibold text-danger",
};

/**
 * A labelled input whose hint and error are announced through aria-describedby. Icons and
 * trailing controls sit inside the input's box but outside its label, so the label stays
 * plain text and no control is nested in another.
 */
export function TextField({
  id,
  label,
  error,
  hint,
  leadingIcon,
  trailing,
  appearance = "workspace",
  className,
  ...input
}: TextFieldProps) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  const site = appearance === "site";

  const inputClass = site
    ? [SITE.input, leadingIcon && "pl-13", trailing && "pr-14", className].filter(Boolean).join(" ")
    : className;
  const control = (
    <input
      id={id}
      className={inputClass}
      aria-invalid={error ? true : undefined}
      aria-describedby={describedBy}
      {...input}
    />
  );

  return (
    <div className={site ? SITE.field : "field"}>
      <label htmlFor={id} className={site ? SITE.label : undefined}>
        {label}
      </label>
      {hint && (
        <p id={hintId} className={site ? SITE.hint : "field-hint"}>
          {hint}
        </p>
      )}
      {leadingIcon || trailing ? (
        <div className="relative">
          {leadingIcon && (
            <span className="pointer-events-none absolute inset-y-0 left-4 flex items-center text-fg-muted">
              {leadingIcon}
            </span>
          )}
          {control}
          {trailing && <span className="absolute inset-y-0 right-1.5 flex items-center">{trailing}</span>}
        </div>
      ) : (
        control
      )}
      {error && (
        <p id={errorId} className={site ? SITE.error : "field-error"}>
          {error}
        </p>
      )}
    </div>
  );
}
