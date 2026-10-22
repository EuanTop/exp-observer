import { describe, expect, it } from "vitest";
import {
  facingSides,
  routeEdge,
  segmentClear,
  type Rect,
} from "./edge-routing";

const a: Rect = { x: 0, y: 0, width: 280, height: 178 };
const b: Rect = { x: 440, y: 0, width: 280, height: 178 };

describe("card edge routing", () => {
  it("uses side ports and distinct clear lanes for horizontal reciprocal edges", () => {
    const forward = routeEdge(a, b, [], -18)!;
    const backward = routeEdge(b, a, [], 18)!;
    expect([forward.sourceSide, forward.targetSide]).toEqual(["right", "left"]);
    expect([backward.sourceSide, backward.targetSide]).toEqual([
      "left",
      "right",
    ]);
    expect(forward.points[0]).toEqual({ x: a.width, y: a.height / 2 });
    expect(backward.points.at(-1)).toEqual(forward.points[0]);
    expect(forward.points.at(-1)).toEqual({ x: b.x, y: b.height / 2 });
    expect(backward.points[0]).toEqual(forward.points.at(-1));
    expect(forward.points.some((p) => p.y < a.height / 2)).toBe(true);
    expect(backward.points.some((p) => p.y > a.height / 2)).toBe(true);
    for (const route of [forward, backward]) {
      expect(
        route.points
          .slice(1)
          .every((p, index) => segmentClear(route.points[index], p, [a, b])),
      ).toBe(true);
    }
  });

  it("routes around intervening cards and never crosses their interiors", () => {
    const target = { ...b, x: 900 };
    const obstacles = [
      { x: 340, y: -60, width: 160, height: 300 },
      { x: 570, y: 100, width: 160, height: 280 },
    ];
    const route = routeEdge(a, target, obstacles)!;
    expect(route).toBeDefined();
    expect(route.points.length).toBeGreaterThan(3);
    expect(
      route.points
        .slice(1)
        .every((p, index) =>
          segmentClear(route.points[index], p, [a, target, ...obstacles]),
        ),
    ).toBe(true);
  });

  it("changes ports for a dragged node and respects resized container bounds", () => {
    expect(facingSides(a, b)).toEqual(["right", "left"]);
    const moved = { ...b, x: 0, y: 350 };
    expect(facingSides(a, moved)).toEqual(["bottom", "top"]);
    const route = routeEdge(a, moved, [], -18)!;
    expect(route.points[0]).toEqual({ x: a.width / 2, y: a.height });
    expect(route.points.at(-1)).toEqual({
      x: moved.x + moved.width / 2,
      y: moved.y,
    });
    expect(route.points.at(-1)!.y).toBe(moved.y);
    const expanded = { ...a, width: 600, height: 400 };
    const outside = { ...b, x: 820 };
    const expandedRoute = routeEdge(expanded, outside, [])!;
    expect(expandedRoute.points[0].x).toBe(expanded.x + expanded.width);
    const collapsedRoute = routeEdge(a, outside, [])!;
    expect(collapsedRoute.points[0].x).toBe(a.width);
  });
  it("separates vertical return labels and keeps long labels clear of cards", () => {
    const below = { ...b, x: 0, y: 420 };
    const forward = routeEdge(a, below, [], -18, 170)!;
    const back = routeEdge(below, a, [], 18, 170)!;
    expect(Math.abs(forward.label.y - back.label.y)).toBeGreaterThan(24);
    for (const route of [forward, back]) {
      expect(route.label.y - 12).toBeGreaterThan(a.y + a.height);
      expect(route.label.y + 12).toBeLessThan(below.y);
    }
  });
});
