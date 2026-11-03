import { describe, expect, it } from "vitest";

import { ApiError, NetworkError } from "./api/errors";
import {
  mapStaffError,
  removedRoles,
  validateProfile,
  validateRoles,
  validateStaffCreate,
} from "./staff-forms";

const VALID = {
  email: "new.agent@estatehub.example",
  fullName: "New Agent",
  password: "a strong passphrase",
  roles: ["agent"],
};

function apiError(code: string, fields: Record<string, string[]> = {}, status = 409): ApiError {
  return new ApiError({ status, code, message: code, fields, retryAfter: 120 });
}

describe("validateStaffCreate", () => {
  it("accepts valid input", () => {
    expect(validateStaffCreate(VALID)).toEqual({});
  });

  it.each([
    [{ email: "" }, "email", "Enter an email address."],
    [{ email: "not-an-email" }, "email", "Enter a valid email address."],
    [{ fullName: "   " }, "fullName", "Enter the person's full name."],
    [{ fullName: "x".repeat(201) }, "fullName", "Use at most 200 characters."],
    [{ password: "x".repeat(11) }, "password", "Use at least 12 characters."],
    [{ password: "x".repeat(129) }, "password", "Use at most 128 characters."],
    [{ roles: [] }, "roles", "Choose at least one role."],
  ])("rejects %j", (override, field, message) => {
    expect(validateStaffCreate({ ...VALID, ...override })).toEqual({ [field]: message });
  });

  it("counts password characters, not UTF-16 units", () => {
    expect(validateStaffCreate({ ...VALID, password: "🔐".repeat(12) })).toEqual({});
  });
});

describe("profile and role validation", () => {
  it("validates profile edits without a password", () => {
    expect(validateProfile({ email: VALID.email, fullName: "Renamed" })).toEqual({});
  });

  it("requires a role", () => {
    expect(validateRoles([])).toEqual({ roles: "Choose at least one role." });
  });

  it("lists removed roles", () => {
    expect(removedRoles(["administrator", "agent"], ["agent", "manager"])).toEqual([
      "administrator",
    ]);
    expect(removedRoles(["agent"], ["agent", "manager"])).toEqual([]);
  });
});

describe("mapStaffError", () => {
  it("maps a duplicate email to the email field", () => {
    expect(mapStaffError(apiError("email_already_exists"))).toEqual({
      fields: { email: "A staff member with this email already exists." },
      message: null,
    });
  });

  it.each([
    ["last_administrator", /At least one active administrator must remain/],
    ["self_lockout", /cannot disable your own account/],
    ["permission_denied", /do not have permission/],
    ["not_found", /no longer exists/],
    ["auth_rate_limited", /Try again in 2 minutes/],
  ])("explains %s", (code, message) => {
    const mapped = mapStaffError(apiError(code));
    expect(mapped.fields).toEqual({});
    expect(mapped.message).toMatch(message);
  });

  it("maps validation errors to form fields, including nested paths", () => {
    const error = apiError(
      "validation_error",
      {
        full_name: ["Value error, Name must not contain control characters."],
        "roles.0": ["Input should be 'administrator', 'manager', 'agent' or 'accountant'"],
      },
      422,
    );

    expect(mapStaffError(error)).toEqual({
      fields: {
        fullName: "Name must not contain control characters.",
        roles: "Input should be 'administrator', 'manager', 'agent' or 'accountant'",
      },
      message: null,
    });
  });

  it("never shows unknown fields or raw bodies", () => {
    const error = apiError("validation_error", { token_version: ["Extra inputs"] }, 422);

    expect(mapStaffError(error)).toEqual({
      fields: {},
      message: "Some details are invalid. Check the form and try again.",
    });
    expect(mapStaffError(apiError("internal_error", {}, 500)).message).toBe(
      "The change could not be saved. Please try again.",
    );
  });

  it("explains connection problems", () => {
    expect(mapStaffError(new NetworkError()).message).toMatch(/could not be reached/);
    expect(mapStaffError(new Error("boom")).message).toBe("Something went wrong. Please try again.");
  });
});
