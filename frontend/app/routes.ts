import { type RouteConfig, index, route } from "@react-router/dev/routes";

export default [
  index("routes/landing.tsx"),
  route("login", "routes/login.tsx"),
  route("workspace", "routes/home.tsx"),
  route("workspace/:scriptId", "routes/workspace.tsx"),
  route("novels/:novelId", "routes/novel-page.tsx"),
  route("dashboard", "routes/dashboard.tsx"),
] satisfies RouteConfig;
