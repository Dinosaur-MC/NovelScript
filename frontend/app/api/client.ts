import { ApiError, getAuthToken } from "./types";
import type { ApiResponse } from "./types";

/** Configurable via VITE_API_BASE_URL env var; defaults to relative /api/v1. */
const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1";
const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * Thin fetch wrapper for the v1 REST API.
 * - Prepends /api/v1
 * - Attaches Authorization header when a token exists
 * - Throws ApiError on non-success responses
 * - Supports AbortController for timeout
 */
export async function request<T>(
  path: string,
  options: RequestInit & { timeout?: number } = {},
): Promise<T> {
  const { timeout = DEFAULT_TIMEOUT_MS, ...fetchOpts } = options;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  const token = getAuthToken();

  const headers: Record<string, string> = {};
  if (!(fetchOpts.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      ...fetchOpts,
      headers: { ...headers, ...(fetchOpts.headers as Record<string, string> | undefined) },
      signal: controller.signal,
    });

    const json: ApiResponse<T> = await res.json();

    if (json.code !== 200 && json.code !== 0) {
      throw new ApiError(res.status, json.code, json.message);
    }

    return json.data;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if ((err as Error).name === "AbortError") {
      throw new ApiError(0, 0, "请求超时，请检查网络");
    }
    throw new ApiError(0, 0, (err as Error).message || "网络不可达");
  } finally {
    clearTimeout(timer);
  }
}
