import { type RouteConfig, index, route } from "@react-router/dev/routes";

export default [
  index("routes/home.tsx"),
  route("workspace/:taskId", "routes/workspace.tsx"),
] satisfies RouteConfig;
