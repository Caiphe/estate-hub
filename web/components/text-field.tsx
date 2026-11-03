import type { InputHTMLAttributes } from "react";

type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> & {
  id: string;
  label: string;
  error?: string;
  hint?: string;
};

/** A labelled input whose hint and error are announced through aria-describedby. */
export function TextField({ id, label, error, hint, ...input }: TextFieldProps) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {hint && (
        <p id={hintId} className="field-hint">
          {hint}
        </p>
      )}
      <input id={id} aria-invalid={error ? true : undefined} aria-describedby={describedBy} {...input} />
      {error && (
        <p id={errorId} className="field-error">
          {error}
        </p>
      )}
    </div>
  );
}
