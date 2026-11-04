import { describe, expect, it, vi } from "vitest";

import { STAFF_SUMMARY } from "../dashboard";
import { staffRevision } from "../staff-changes";

import { ApiClient } from "./client";
import { ApiError } from "./errors";
import { staffApi } from "./staff";

const MEMBER = {
  id: "7d9f1f6c-3a1b-4c55-9a51-0f4b6f5f6a10",
  email: "ada@estatehub.example",
  full_name: "Ada Agent",
  status: "active",
  roles: ["agent"],
  last_login_at: null,
  created_at: "2026-11-03T09:00:00Z",
  updated_at: "2026-11-03T09:00:00Z",
};

function respond(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** A staff API over a fake fetch that answers every request with `reply`. */
function api(reply: (url: URL, method: string) => Response) {
  const requests: Array<{ url: URL; method: string; signal?: AbortSignal | null }> = [];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = init?.method ?? "GET";
    requests.push({ url, method, signal: init?.signal });
    return reply(url, method);
  });
  const client = new ApiClient({ fetch: fetchImpl as unknown as typeof fetch, readCookie: () => "csrf" });
  return { staff: staffApi(client), requests };
}

const page = (total: number) => ({ items: total ? [MEMBER] : [], total, limit: 1, offset: 0 });

describe("staffApi.count", () => {
  it.each([
    ["total", ""],
    ["active", "status=active&limit=1"],
    ["disabled", "status=disabled&limit=1"],
    ["administrators", "role=administrator&limit=1"],
  ])("the %s card asks for one row with its filters", async (id, search) => {
    const { staff, requests } = api(() => respond(200, page(7)));
    const card = STAFF_SUMMARY.find((item) => item.id === id)!;

    expect(await staff.count(card.filters)).toBe(7);
    expect(requests).toHaveLength(1);
    expect(requests[0].url.pathname).toBe("/api/v1/staff");
    expect(requests[0].url.search).toBe(`?${search || "limit=1"}`);
  });

  it("returns the page total, not the number of rows fetched", async () => {
    const { staff } = api(() => respond(200, page(149)));
    expect(await staff.count({})).toBe(149);
  });

  it("returns zero for an empty result", async () => {
    const { staff } = api(() => respond(200, page(0)));
    expect(await staff.count({ status: "disabled" })).toBe(0);
  });

  it("passes the abort signal through", async () => {
    const { staff, requests } = api(() => respond(200, page(1)));
    const controller = new AbortController();
    await staff.count({}, controller.signal);
    expect(requests[0].signal).toBe(controller.signal);
  });

  it("surfaces a forbidden response as an ApiError", async () => {
    const { staff } = api(() =>
      respond(403, { error: { code: "permission_denied", message: "No", fields: {}, request_id: "r" } }),
    );
    await expect(staff.count({})).rejects.toMatchObject({ status: 403 });
    await expect(staff.count({})).rejects.toBeInstanceOf(ApiError);
  });
});

describe("staff mutations", () => {
  const ID = MEMBER.id;
  const mutations = {
    create: (staff: ReturnType<typeof staffApi>) =>
      staff.create({ email: "a@b.example", fullName: "A", password: "long enough pass", roles: ["agent"] }),
    updateProfile: (staff: ReturnType<typeof staffApi>) => staff.updateProfile(ID, { fullName: "B" }),
    replaceRoles: (staff: ReturnType<typeof staffApi>) => staff.replaceRoles(ID, ["manager"]),
    disable: (staff: ReturnType<typeof staffApi>) => staff.disable(ID),
    reactivate: (staff: ReturnType<typeof staffApi>) => staff.reactivate(ID),
    revokeSessions: (staff: ReturnType<typeof staffApi>) => staff.revokeSessions(ID),
  };

  it.each(Object.entries(mutations))("%s marks staff data as changed when it succeeds", async (name, run) => {
    const { staff } = api(() => (name === "revokeSessions" ? respond(204, null) : respond(200, MEMBER)));
    const before = staffRevision();
    await run(staff);
    expect(staffRevision()).toBe(before + 1);
  });

  it.each(Object.entries(mutations))("%s leaves staff data unchanged when it fails", async (_name, run) => {
    const { staff } = api(() =>
      respond(409, { error: { code: "last_administrator", message: "No", fields: {}, request_id: "r" } }),
    );
    const before = staffRevision();
    await expect(run(staff)).rejects.toBeInstanceOf(ApiError);
    expect(staffRevision()).toBe(before);
  });

  it("reads never mark staff data as changed", async () => {
    const { staff } = api((url) => respond(200, url.pathname.endsWith("/staff") ? page(1) : MEMBER));
    const before = staffRevision();
    await staff.count({});
    await staff.list({});
    await staff.get(ID);
    expect(staffRevision()).toBe(before);
  });
});
