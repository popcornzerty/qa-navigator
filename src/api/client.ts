/**
 * REST API abstraction.
 *
 * The app talks to the Python/FastAPI engine by default. The in-memory mock
 * implementations from Phase 1 are still available for demos and for working on the UI
 * without a backend, but they are opt-in: set VITE_API_MODE=mock to use them. Defaulting
 * to the mock would mean a misconfigured environment silently shows fictional data.
 */

export type ApiMode = "mock" | "http";

export const API_MODE: ApiMode =
  ((import.meta.env["VITE_API_MODE"] as ApiMode | undefined) ?? "http") === "mock"
    ? "mock"
    : "http";

// `.env.local` is gitignored, so this default is what a fresh clone actually uses: the
// QA engine running on this machine. Override it for a deployed backend.
export const API_BASE_URL: string =
  (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? "http://127.0.0.1:8000/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });

  if (!response.ok) {
    // FastAPI puts the actionable message in `detail`; without it the UI can only say
    // "request failed", which hides things the user is expected to fix themselves.
    throw new ApiError(await errorMessage(response, path, init?.method), response.status);
  }

  return (await response.json()) as T;
}

async function errorMessage(response: Response, path: string, method = "GET"): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail.trim()) return body.detail;
  } catch {
    // Not a JSON error payload — fall through to the generic message.
  }
  return `${method} ${path} failed (${response.status})`;
}

export function latency(ms = 180): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Picks the mock or the real implementation depending on the configured mode. */
export async function resolve<T>(mock: () => Promise<T>, real: () => Promise<T>): Promise<T> {
  if (API_MODE === "mock") {
    await latency();
    return mock();
  }
  return real();
}

export function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}
