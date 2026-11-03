import { ApiError, NetworkError, RefreshUnavailableError } from "./api/errors";
import { characterCount, formatWait } from "./format";

export const PASSWORD_MIN = 12;
export const PASSWORD_MAX = 128;
const NAME_MAX = 200;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export type FieldErrors = Record<string, string>;

export type StaffValues = { email: string; fullName: string; password: string; roles: string[] };

export function validateProfile(values: { email: string; fullName: string }): FieldErrors {
  const errors: FieldErrors = {};
  if (!values.email.trim()) errors.email = "Enter an email address.";
  else if (!EMAIL_PATTERN.test(values.email.trim())) errors.email = "Enter a valid email address.";
  const name = values.fullName.trim();
  if (!name) errors.fullName = "Enter the person's full name.";
  else if (characterCount(name) > NAME_MAX) errors.fullName = `Use at most ${NAME_MAX} characters.`;
  return errors;
}

export function validateRoles(roles: string[]): FieldErrors {
  return roles.length ? {} : { roles: "Choose at least one role." };
}

export function validateStaffCreate(values: StaffValues): FieldErrors {
  const errors = { ...validateProfile(values), ...validateRoles(values.roles) };
  const length = characterCount(values.password);
  if (length < PASSWORD_MIN) errors.password = `Use at least ${PASSWORD_MIN} characters.`;
  else if (length > PASSWORD_MAX) errors.password = `Use at most ${PASSWORD_MAX} characters.`;
  return errors;
}

// API field names (and nested paths such as "roles.0") to form field names.
const FIELD_NAMES: Record<string, string> = {
  email: "email",
  full_name: "fullName",
  password: "password",
  roles: "roles",
};

/** What the form shows for a failed request: messages by field, plus a form message. */
export type MappedError = { fields: FieldErrors; message: string | null };

/**
 * Turn an API failure into form feedback. Conflict and permission messages are stated
 * plainly; unexpected errors never echo raw response bodies.
 */
export function mapStaffError(error: unknown): MappedError {
  if (!(error instanceof ApiError)) {
    if (error instanceof NetworkError || error instanceof RefreshUnavailableError) {
      return { fields: {}, message: error.message };
    }
    return { fields: {}, message: "Something went wrong. Please try again." };
  }
  switch (error.code) {
    case "email_already_exists":
      return { fields: { email: "A staff member with this email already exists." }, message: null };
    case "last_administrator":
      return {
        fields: {},
        message: "At least one active administrator must remain. Make someone else an administrator first.",
      };
    case "self_lockout":
      return {
        fields: {},
        message: "You cannot disable your own account or remove your own administrator role.",
      };
    case "permission_denied":
      return { fields: {}, message: "You do not have permission to make this change." };
    case "not_found":
      return { fields: {}, message: "This staff member no longer exists." };
    case "auth_rate_limited":
      return { fields: {}, message: `Too many attempts. Try again in ${formatWait(error.retryAfter)}.` };
    case "validation_error": {
      const fields: FieldErrors = {};
      for (const [name, messages] of Object.entries(error.fields)) {
        const field = FIELD_NAMES[name.split(".")[0]];
        if (field && messages[0] && !fields[field]) {
          fields[field] = messages[0].replace(/^Value error, /, "");
        }
      }
      return Object.keys(fields).length
        ? { fields, message: null }
        : { fields: {}, message: "Some details are invalid. Check the form and try again." };
    }
    default:
      return { fields: {}, message: "The change could not be saved. Please try again." };
  }
}

/** Roles in `before` that `after` drops; removing roles requires confirmation. */
export function removedRoles(before: string[], after: string[]): string[] {
  const kept = new Set(after);
  return before.filter((role) => !kept.has(role));
}
