import { type EntryContext } from "react-router";
import { ServerRouter } from "react-router";
import { renderToString } from "react-dom/server";
import { createCache, extractStyle, StyleProvider } from "@ant-design/cssinjs";

export default function handleRequest(
  request: Request,
  responseStatusCode: number,
  responseHeaders: Headers,
  routerContext: EntryContext,
) {
  const cache = createCache();

  const html = renderToString(
    <StyleProvider cache={cache}>
      <ServerRouter context={routerContext} url={request.url} />
    </StyleProvider>,
  );

  const styleText = extractStyle(cache);

  // Inject extracted antd cssinjs styles before </head>
  const finalHtml = html.replace(
    "</head>",
    `<style data-antd="true">${styleText}</style></head>`,
  );

  const headers = new Headers(responseHeaders);
  headers.set("Content-Type", "text/html");

  return new Response(`<!DOCTYPE html>${finalHtml}`, {
    status: responseStatusCode,
    headers,
  });
}
