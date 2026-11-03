import { ROLE_OPTIONS } from "@/lib/api/staff";

type RoleCheckboxesProps = {
  idPrefix: string;
  value: string[];
  onChange: (roles: string[]) => void;
  error?: string;
  disabled?: boolean;
};

export function RoleCheckboxes({ idPrefix, value, onChange, error, disabled }: RoleCheckboxesProps) {
  const errorId = `${idPrefix}-roles-error`;
  const toggle = (code: string, checked: boolean) =>
    onChange(checked ? [...value, code] : value.filter((role) => role !== code));

  return (
    <fieldset
      className="fieldset"
      aria-describedby={error ? errorId : undefined}
      aria-invalid={error ? true : undefined}
    >
      <legend>Roles</legend>
      {ROLE_OPTIONS.map((role) => (
        <label key={role.code} className="checkbox">
          <input
            type="checkbox"
            checked={value.includes(role.code)}
            onChange={(event) => toggle(role.code, event.target.checked)}
            disabled={disabled}
          />
          {role.label}
        </label>
      ))}
      {error && (
        <p id={errorId} className="field-error">
          {error}
        </p>
      )}
    </fieldset>
  );
}

export function roleLabel(code: string): string {
  return ROLE_OPTIONS.find((role) => role.code === code)?.label ?? code;
}
