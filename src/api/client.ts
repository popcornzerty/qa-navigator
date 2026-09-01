/**
 * REST API abstraction.
 *
 * Phase 1 runs against in-memory mock implementations. Switching to the
 * Python/FastAPI backend only requires setting VITE_API_MODE=http and
 * VITE_API_BASE_URL — no UI changes.
 */

export type ApiMode = "mock" | "http";

export const API_MODE: ApiMode =
  ((import.meta.env["VITE_API_MODE"] as ApiMode | undefined) ?? "mock") === "http"
    ? "http"
    : "mock";

export const API_BASE_URL: string =
  (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? "/api/v1";

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
    throw new ApiError(`${init?.method ?? "GET"} ${path} failed`, response.status);
  }

  return (await response.json()) as T;
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
