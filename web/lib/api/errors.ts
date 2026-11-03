/** The API's standard error body: {"error": {code, message, fields, request_id}}. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields: Record<string, string[]>;
  readonly requestId: string | null;
  /** Seconds from `Retry-After`, when the API sent one. */
  readonly retryAfter: number | null;

  constructor(init: {
    status: number;
    code: string;
    message: string;
    fields?: Record<string, string[]>;
    requestId?: string | null;
    retryAfter?: number | null;
  }) {
    super(init.message);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.fields = init.fields ?? {};
    this.requestId = init.requestId ?? null;
    this.retryAfter = init.retryAfter ?? null;
  }
}

/** The request never produced an HTTP response (offline, DNS, aborted). */
export class NetworkError extends Error {
  constructor() {
    super("The server could not be reached. Check your connection and try again.");
    this.name = "NetworkError";
  }
}

function isFieldMap(value: unknown): value is Record<string, string[]> {
  return (
    typeof value === "object" &&
    value !== null &&
    Object.values(value).every(
      (messages) => Array.isArray(messages) && messages.every((m) => typeof m === "string"),
    )
  );
}

function parseRetryAfter(header: string | null): number | null {
  if (!header) return null;
  const seconds = Number.parseInt(header, 10);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

/** Build an ApiError from any failed response, tolerating non-standard bodies. */
export async function toApiError(response: Response): Promise<ApiError> {
  let error: Record<string, unknown> = {};
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "error" in body) {
      const candidate = (body as { error: unknown }).error;
      if (typeof candidate === "object" && candidate !== null) {
        error = candidate as Record<string, unknown>;
      }
    }
  } catch {
    // Not JSON (for example a proxy error page); fall back to generic values.
  }
  return new ApiError({
    status: response.status,
    code: typeof error.code === "string" ? error.code : "http_error",
    message:
      typeof error.message === "string" ? error.message : "The request could not be completed.",
    fields: isFieldMap(error.fields) ? error.fields : {},
    requestId: typeof error.request_id === "string" ? error.request_id : null,
    retryAfter: parseRetryAfter(response.headers.get("Retry-After")),
  });
}

/** The session could not be refreshed right now (offline, rate limited, server error). */
export class RefreshUnavailableError extends Error {
  constructor() {
    super("Your session could not be renewed right now. Please try again.");
    this.name = "RefreshUnavailableError";
  }
}
