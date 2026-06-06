import { createCache } from "@ant-design/cssinjs";
import type Cache from "@ant-design/cssinjs/es/Cache";

/** Module-level singleton — populated during SSR render, extracted after. */
let _cache: ReturnType<typeof createCache> | null = null;

export function getSSRCache(): Cache {
  if (!_cache) _cache = createCache();
  return _cache;
}

/** The current cache instance — entry.server.tsx calls extractStyle() on it after render. */
export function getCacheForExtraction(): ReturnType<typeof createCache> | null {
  return _cache;
}
