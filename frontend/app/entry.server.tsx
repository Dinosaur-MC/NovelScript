import { PassThrough } from "node:stream";

import { createReadableStreamFromReadable } from "@react-router/node";
import { ServerRouter } from "react-router";
import { renderToPipeableStream } from "react-dom/server";
import { extractSSRStyles } from "./lib/ssr-cache";
import type { EntryContext } from "react-router";

export const streamTimeout = 5_000;

export default function handleRequest(
  request: Request,
  responseStatusCode: number,
  responseHeaders: Headers,
  routerContext: EntryContext,
) {
  if (request.method.toUpperCase() === "HEAD") {
    return new Response(null, {
      status: responseStatusCode,
      headers: responseHeaders,
    });
  }

  // StyleProvider lives inside root.tsx (via getSSRCache).
  // No extra wrapper here — keeps SSR & client component trees identical.
  return new Promise((resolve, reject) => {
    let settled = false;
    const timeoutId = setTimeout(() => {
      if (!settled) {
        settled = true;
        reject(new Error("SSR render timed out"));
      }
    }, streamTimeout);

    const { pipe, abort } = renderToPipeableStream(
      <ServerRouter context={routerContext} url={request.url} />,
      {
        onAllReady() {
          if (settled) return;

          const chunks: Buffer[] = [];
          const collector = new PassThrough();
          collector.on("data", (chunk: Buffer) => chunks.push(chunk));
          collector.on("end", () => {
            let html = Buffer.concat(chunks).toString("utf-8");

            const styleText = extractSSRStyles();
            if (styleText) {
              html = html.replace(
                "</head>",
                `<style data-ssr>${styleText}</style></head>`,
              );
            }

            settled = true;
            clearTimeout(timeoutId);

            const body = new PassThrough();
            body.end(Buffer.from(html, "utf-8"));
            const stream = createReadableStreamFromReadable(body);
            responseHeaders.set("Content-Type", "text/html; charset=utf-8");
            responseHeaders.delete("Content-Length");
            resolve(
              new Response(stream, {
                headers: responseHeaders,
                status: responseStatusCode,
              }),
            );
          });
          pipe(collector);
        },
        onShellError(err: unknown) {
          if (!settled) {
            settled = true;
            clearTimeout(timeoutId);
            reject(err);
          }
        },
        onError(err: unknown) {
          responseStatusCode = 500;
          console.error("SSR error:", err);
        },
      },
    );
  });
}
