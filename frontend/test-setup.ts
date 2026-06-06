import "@testing-library/jest-dom/vitest";

// jsdom's requestAnimationFrame is often a no-op stub — force proper polyfill
globalThis.requestAnimationFrame = (cb: FrameRequestCallback) =>
  setTimeout(cb, 0) as unknown as number;
