import { describe, it, expect, vi, beforeEach } from "vitest";
import { useAuthStore } from "../../stores/auth-store";

vi.mock("../../api/auth", () => ({
  me: vi.fn(),
}));

import { me } from "../../api/auth";

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: null, loaded: false });
  localStorage.removeItem("auth_token");
});

describe("auth-store", () => {
  it("starts with user=null, loaded=false", () => {
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().loaded).toBe(false);
  });

  it("setUser stores user and marks loaded", () => {
    useAuthStore.getState().setUser({ id: "u1", username: "Alice", role: "user" });
    expect(useAuthStore.getState().user?.username).toBe("Alice");
    expect(useAuthStore.getState().loaded).toBe(true);
  });

  it("clearUser removes token and resets user", () => {
    localStorage.setItem("auth_token", "test-token");
    useAuthStore.getState().setUser({ id: "u1", username: "Bob", role: "user" });
    useAuthStore.getState().clearUser();
    expect(useAuthStore.getState().user).toBeNull();
    expect(localStorage.getItem("auth_token")).toBeNull();
  });

  it("fetchUser skips when no token", async () => {
    await useAuthStore.getState().fetchUser();
    expect(me).not.toHaveBeenCalled();
    expect(useAuthStore.getState().loaded).toBe(true);
  });

  it("fetchUser calls /me when token exists", async () => {
    localStorage.setItem("auth_token", "valid-token");
    vi.mocked(me).mockResolvedValueOnce({ id: "u1", username: "Eve", role: "user" });

    await useAuthStore.getState().fetchUser();

    expect(me).toHaveBeenCalled();
    expect(useAuthStore.getState().user?.username).toBe("Eve");
    expect(useAuthStore.getState().loaded).toBe(true);
  });

  it("fetchUser handles API failure gracefully", async () => {
    localStorage.setItem("auth_token", "expired-token");
    vi.mocked(me).mockRejectedValueOnce(new Error("401"));

    await useAuthStore.getState().fetchUser();
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().loaded).toBe(true);
  });
});
