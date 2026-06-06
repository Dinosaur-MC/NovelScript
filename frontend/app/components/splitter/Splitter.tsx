import { useRef, useCallback, useState, type ReactNode } from "react";

interface SplitterProps {
  direction?: "horizontal" | "vertical";
  /** Initial percentage for the first child (0–100). */
  initialLeftPercent?: number;
  /** Minimum pixel widths. */
  minLeftPx?: number;
  minRightPx?: number;
  /** Called after drag ends with the new left percentage (0–100). */
  onResize?: (leftPercent: number) => void;
  children: [ReactNode, ReactNode];
}

const HANDLE_SIZE = 4;

/**
 * Two-pane splitter. Drag the 4px handle to resize.
 */
export function Splitter({
  direction = "horizontal",
  initialLeftPercent = 50,
  minLeftPx = 200,
  minRightPx = 200,
  onResize,
  children,
}: SplitterProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [leftPct, setLeftPct] = useState(initialLeftPercent);
  const dragging = useRef(false);
  const latestPct = useRef(leftPct);

  const onMouseDown = useCallback(() => {
    dragging.current = true;
    document.body.style.cursor = direction === "horizontal" ? "col-resize" : "row-resize";
    document.body.style.userSelect = "none";

    const onMove = (e: MouseEvent) => {
      if (!dragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const total = direction === "horizontal" ? rect.width : rect.height;
      const pos = direction === "horizontal" ? e.clientX - rect.left : e.clientY - rect.top;
      const pct = (pos / total) * 100;
      const minLPct = (minLeftPx / total) * 100;
      const minRPct = (minRightPx / total) * 100;
      const clamped = Math.max(minLPct, Math.min(100 - minRPct, pct));
      setLeftPct(clamped);
      latestPct.current = clamped;
    };

    const onUp = () => {
      dragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      onResize?.(latestPct.current);
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }, [direction, minLeftPx, minRightPx, onResize]);

  const isH = direction === "horizontal";

  return (
    <div
      ref={containerRef}
      style={{
        display: "flex",
        flexDirection: isH ? "row" : "column",
        width: "100%",
        height: "100%",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          [isH ? "width" : "height"]: `${leftPct}%`,
          overflow: "hidden",
        }}
      >
        {children[0]}
      </div>
      <div
        onMouseDown={onMouseDown}
        style={{
          [isH ? "width" : "height"]: HANDLE_SIZE,
          cursor: isH ? "col-resize" : "row-resize",
          backgroundColor: "var(--color-border-subtle)",
          flexShrink: 0,
          transition: "background-color 0.15s",
        }}
        onMouseEnter={(e) => {
          (e.target as HTMLElement).style.backgroundColor = "var(--color-accent-primary)";
        }}
        onMouseLeave={(e) => {
          (e.target as HTMLElement).style.backgroundColor = "var(--color-border-subtle)";
        }}
      />
      <div style={{ flex: 1, overflow: "hidden" }}>{children[1]}</div>
    </div>
  );
}
