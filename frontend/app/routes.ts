import { type RouteConfig, index, route } from "@react-router/dev/routes";

export default [
  index("routes/home.tsx"),
  route("login", "routes/login.tsx"),
  route("workspace/:scriptId", "routes/workspace.tsx"),
  route("dashboard", "routes/dashboard.tsx"),
] satisfies RouteConfig;
