/**
 * Production server wrapper for the React Router 7 SSR app.
 *
 * Proxies `/api/v1/*` requests to the backend API so that only the
 * frontend port needs to be exposed.  The API URL is configured via the
 * `API_URL` environment variable (defaults to `http://localhost:8000` for
 * Docker bridge network compatibility).
 *
 * Usage:
 *   node server.prod.mjs
 *   API_URL=http://api:8000 PORT=3000 node server.prod.mjs
 */

import { createRequestListener } from "@react-router/node";
import http from "node:http";

const PORT = process.env.PORT || 3000;
const API_URL = process.env.API_URL || "http://localhost:8000";

// ---- load the built React Router server bundle --------------------------
const buildPath = new URL("./build/server/index.js", import.meta.url).pathname;
const build = await import(buildPath);
const rrHandler = createRequestListener({ build });

// ---- API proxy helper ---------------------------------------------------
function proxyApi(req, res) {
  const target = new URL(req.url, API_URL);
  const options = {
    hostname: target.hostname,
    port: target.port || 8000,
    path: target.pathname + target.search,
    method: req.method,
    headers: { ...req.headers, host: target.host },
  };

  const proxyReq = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res);
  });

  proxyReq.on("error", (err) => {
    console.error("API proxy error:", err.message);
    res.writeHead(502, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ code: 502, message: "Backend unavailable" }));
  });

  req.pipe(proxyReq);
}

// ---- unified request handler --------------------------------------------
const server = http.createServer((req, res) => {
  if (req.url?.startsWith("/api/v1/")) {
    return proxyApi(req, res);
  }
  rrHandler(req, res);
});

server.listen(PORT, () => {
  console.log(`NovelScript frontend running on http://localhost:${PORT}`);
  console.log(`API proxy target: ${API_URL}`);
});
