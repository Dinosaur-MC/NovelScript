import { useEffect } from "react";
import {
  isRouteErrorResponse,
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration,
} from "react-router";

import { ConfigProvider, theme, App as AntApp } from "antd";
import { StyleProvider } from "@ant-design/cssinjs";
import { getSSRCache } from "./ssr-cache";
import { useAuthStore } from "./stores/auth-store";

import type { Route } from "./+types/root";
import "./app.css";

export const links: Route.LinksFunction = () => [
  { rel: "preconnect", href: "https://fonts.googleapis.com" },
  {
    rel: "preconnect",
    href: "https://fonts.gstatic.com",
    crossOrigin: "anonymous",
  },
  {
    rel: "stylesheet",
    href: "https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=Noto+Sans+SC:wght@400;500;700&family=Noto+Serif+SC:wght@400&family=JetBrains+Mono:wght@400&display=swap",
  },
];

export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="zh-CN"
      suppressHydrationWarning
      className="ns-layout-html"
    >
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <Meta />
        <Links />
      </head>
      <body className="ns-layout-body">
        {children}
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  );
}

export default function App() {
  const { fetchUser, loaded } = useAuthStore();

  useEffect(() => {
    if (!loaded) fetchUser();
  }, [fetchUser, loaded]);

  return (
    <StyleProvider cache={getSSRCache()}>
      <ConfigProvider
        theme={{
          cssVar: { prefix: "ns" },
          algorithm: theme.darkAlgorithm,
          token: {
            colorPrimary: "#6c5ce7",
            colorSuccess: "#00cec9",
            colorWarning: "#fdcb6e",
            colorError: "#e17055",
            colorInfo: "#74b9ff",
            colorTextBase: "#e8e8f0",
            colorBgBase: "#0a0a0f",
            colorBgContainer: "#14141f",
            colorBgElevated: "#1c1c2a",
            colorBorder: "#2a2a3e",
            colorBorderSecondary: "#2a2a3e",
            borderRadius: 6,
          },
        }}
      >
        <AntApp>
          <Outlet />
        </AntApp>
      </ConfigProvider>
    </StyleProvider>
  );
}

export function ErrorBoundary({ error }: Route.ErrorBoundaryProps) {
  let message = "Oops!";
  let details = "An unexpected error occurred.";
  let stack: string | undefined;

  if (isRouteErrorResponse(error)) {
    message = error.status === 404 ? "404" : "Error";
    details =
      error.status === 404
        ? "The requested page could not be found."
        : error.statusText || details;
  } else if (import.meta.env.DEV && error && error instanceof Error) {
    details = error.message;
    stack = error.stack;
  }

  return (
    <main className="ns-error-wrap">
      <h1 className="ns-error-title">{message}</h1>
      <p className="ns-error-detail">{details}</p>
      {stack && (
        <pre
          className="ns-error-stack"
        >
          <code>{stack}</code>
        </pre>
      )}
    </main>
  );
}
