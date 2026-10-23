import type { NodePresentation } from "./node-presentation";

// Initial geometry before ResizeObserver reports the actual rendered height.
// CSS wraps the same content naturally; these estimates never fix card height.
export function estimateCardHeight(p: NodePresentation, width = 368): number {
  const lines = (s: string, font: number, max: number) =>
    Math.min(
      max,
      s
        .split("\n")
        .reduce(
          (sum, line) =>
            sum +
            Math.max(
              1,
              Math.ceil(
                [...line].reduce(
                  (n, c) => n + (c.charCodeAt(0) > 255 ? font : font * 0.56),
                  0,
                ) /
                  (width - 40),
              ),
            ),
          0,
        ),
    );
  return Math.ceil(
    103 +
      lines(p.headline, 16, 3) * 24 +
      (p.summary ? 8 + lines(p.summary, 12, p.conclusion ? 2 : 4) * 19.2 : 0) +
      (p.conclusion
        ? 4 + lines(`${p.source || "结论"}：${p.conclusion}`, 12, 2) * 19.2
        : 0),
  );
}
