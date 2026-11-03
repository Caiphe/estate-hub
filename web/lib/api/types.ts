/**
 * API response types with runtime validation. API responses are external data, so the
 * shapes the workspace relies on are checked before use.
 */

export class ResponseShapeError extends Error {
  constructor(what: string) {
    super(`Unexpected ${what} response from the API.`);
    this.name = "ResponseShapeError";
  }
}

export type UserStatus = "active" | "disabled";

export type CurrentUser = {
  id: string;
  email: string;
  fullName: string;
  status: UserStatus;
  roles: string[];
  lastLoginAt: string | null;
};

export type EffectivePermissions = {
  roles: string[];
  permissions: string[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

export function parseCurrentUser(data: unknown): CurrentUser {
  if (
    !isRecord(data) ||
    typeof data.id !== "string" ||
    typeof data.email !== "string" ||
    typeof data.full_name !== "string" ||
    (data.status !== "active" && data.status !== "disabled") ||
    !isStringArray(data.roles) ||
    !(data.last_login_at === null || typeof data.last_login_at === "string")
  ) {
    throw new ResponseShapeError("user");
  }
  return {
    id: data.id,
    email: data.email,
    fullName: data.full_name,
    status: data.status,
    roles: data.roles,
    lastLoginAt: data.last_login_at,
  };
}

export function parseEffectivePermissions(data: unknown): EffectivePermissions {
  if (!isRecord(data) || !isStringArray(data.roles) || !isStringArray(data.permissions)) {
    throw new ResponseShapeError("permissions");
  }
  return { roles: data.roles, permissions: data.permissions };
}
