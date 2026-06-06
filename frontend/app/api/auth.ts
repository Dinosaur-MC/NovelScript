import { request } from "./client";

export interface User {
  id: string;
  username: string;
  email?: string;
  role: string;
}

export interface LoginResult {
  token: string;
  user: User;
}

export interface RegisterResult {
  user_id: string;
  username: string;
}

export function login(email: string, password: string) {
  return request<LoginResult>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function register(username: string, email: string, password: string) {
  return request<RegisterResult>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, email, password }),
  });
}

export function logout() {
  return request<null>("/auth/logout", { method: "POST" });
}

export function me() {
  return request<User>("/auth/me");
}
