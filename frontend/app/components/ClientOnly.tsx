import { useState, useEffect, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** Shown during SSR and the brief moment before hydration. */
  fallback?: ReactNode;
}

/** Renders children only on the client, preventing SSR flash for
 *  components that depend on client-only CSS-in-JS styles. */
export function ClientOnly({ children, fallback = null }: Props) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return <>{fallback}</>;
  return <>{children}</>;
}
