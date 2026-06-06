import { PassThrough } from "node:stream";

import { createReadableStreamFromReadable } from "@react-router/node";
import { ServerRouter } from "react-router";
import { renderToPipeableStream } from "react-dom/server";
import { createCache, extractStyle, StyleProvider } from "@ant-design/cssinjs";
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

  // Single render pass: StyleProvider collects all antd css-in-js styles
  // into the shared cache during renderToPipeableStream.
  const cssCache = createCache();

  return new Promise((resolve, reject) => {
    let settled = false;
    const timeoutId = setTimeout(() => {
      if (!settled) {
        settled = true;
        reject(new Error("SSR render timed out"));
      }
    }, streamTimeout);

    const { pipe, abort } = renderToPipeableStream(
      <StyleProvider cache={cssCache}>
        <ServerRouter context={routerContext} url={request.url} />
      </StyleProvider>,
      {
        onAllReady() {
          if (settled) return;

          // Buffer the entire stream so we can inject styles before </head>
          const chunks: Buffer[] = [];
          const collector = new PassThrough();
          collector.on("data", (chunk: Buffer) => chunks.push(chunk));
          collector.on("end", () => {
            let html = Buffer.concat(chunks).toString("utf-8");

            const styleText = extractStyle(cssCache, { plain: true });
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
