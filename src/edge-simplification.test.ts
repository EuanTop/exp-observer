import { describe, expect, it } from "vitest";
import { straightenRoute } from "./edge-simplification";
import { segmentClear } from "./edge-routing";

describe("unnecessary endpoint bends", () => {
  it("uses a straight vertical connection when both free ports can align", () => {
    const source = { x: 300, y: 0, width: 368, height: 150 },
      target = { x: 200, y: 400, width: 368, height: 180 };
    const route = {
      points: [
        { x: 500, y: 150 },
        { x: 500, y: 190 },
        { x: 420, y: 190 },
        { x: 420, y: 400 },
      ],
      label: { x: 395, y: 300 },
    };
    const result = straightenRoute(route, source, target, [], [], 36);
    expect(result.points).toEqual([
      { x: 420, y: 150 },
      { x: 420, y: 400 },
    ]);
    expect(result.label.y).toBeGreaterThan(source.height);
    expect(result.label.y).toBeLessThan(target.y);
  });
  it("removes a final port jog without cutting through an intervening card", () => {
    const source = { x: 500, y: 0, width: 368, height: 150 },
      target = { x: 200, y: 1000, width: 368, height: 160 };
    const obstacle = { x: 400, y: 400, width: 300, height: 180 };
    const route = {
      points: [
        { x: 600, y: 150 },
        { x: 600, y: 190 },
        { x: 300, y: 190 },
        { x: 300, y: 900 },
        { x: 250, y: 900 },
        { x: 250, y: 1000 },
      ],
      label: { x: 275, y: 600 },
    };
    const result = straightenRoute(route, source, target, [obstacle], [], 36);
    expect(result.points.at(-1)).toEqual({ x: 300, y: 1000 });
    expect(result.points.length).toBeLessThan(route.points.length);
    expect(
      result.points
        .slice(1)
        .every((p, i) =>
          segmentClear(result.points[i], p, [source, target, obstacle]),
        ),
    ).toBe(true);
  });
  it("retains bends which actually avoid a card", () => {
    const source = { x: 0, y: 0, width: 368, height: 150 },
      target = { x: 0, y: 600, width: 368, height: 150 },
      obstacle = { x: 0, y: 300, width: 368, height: 150 };
    const route = {
      points: [
        { x: 50, y: 150 },
        { x: 50, y: 180 },
        { x: 450, y: 180 },
        { x: 450, y: 500 },
        { x: 50, y: 500 },
        { x: 50, y: 600 },
      ],
      label: { x: 475, y: 400 },
    };
    expect(
      straightenRoute(route, source, target, [obstacle], [], 36).points,
    ).toEqual(route.points);
  });
  it("never overlays another edge just to make an endpoint straight", () => {
    const source = { x: 0, y: 0, width: 368, height: 150 },
      target = { x: 0, y: 400, width: 368, height: 150 };
    const route = {
      points: [
        { x: 100, y: 150 },
        { x: 100, y: 190 },
        { x: 200, y: 190 },
        { x: 200, y: 400 },
      ],
      label: { x: 175, y: 300 },
    };
    const others = [
      {
        points: [
          { x: 200, y: 150 },
          { x: 200, y: 350 },
        ],
        label: { x: 230, y: 250 },
      },
    ];
    const result = straightenRoute(route, source, target, [], others);
    expect(result.points).not.toEqual([
      { x: 200, y: 150 },
      { x: 200, y: 400 },
    ]);
    expect(result.points[0].x).not.toBe(200);
  });
});
