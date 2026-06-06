/** Generic API response envelope from the backend. */
export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

/** Structured error carrying HTTP status + backend code. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Light-weight auth token getter (P1 — hardcoded session for now). */
export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("auth_token");
}
