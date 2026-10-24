import { describe, expect, it } from "vitest";
import { layoutCanvas } from "./graph-layout";
import { toCanvas, type Project, type ResearchNode } from "./model";
import { segmentClear, type Rect } from "./edge-routing";
import fixture from "./fixtures/urban-invasion-graph.json";

const node = (id: string, patch: Partial<ResearchNode> = {}): ResearchNode => ({
  id,
  title: id,
  kind: "question",
  status: "active",
  parentId: null,
  summary: "",
  notes: "",
  nextAction: "",
  tags: [],
  position: { x: 40, y: 40 },
  positionSource: "auto",
  collapsed: false,
  ...patch,
});
const edge = (source: string, target: string, relation = "branches") => ({
  id: `${source}:${target}:${relation}`,
  source,
  target,
  relation,
});
const project = (
  nodes: ResearchNode[],
  edges: Project["edges"] = [],
): Project => ({
  id: "test",
  name: "test",
  description: "",
  revision: 1,
  createdAt: "",
  updatedAt: "",
  nodes,
  edges,
  runs: [],
  artifacts: [],
  assessments: [],
  decisions: [],
  activity: [],
});
const canvas = (p: Project, scope: string | null = null) =>
  toCanvas(
    p,
    scope,
    [],
    { onToggle() {}, onEnter() {} },
    {
      expandedIds: new Set(
        p.nodes.filter((n) => !n.collapsed).map((n) => n.id),
      ),
    },
  );
const boxes = (result: Awaited<ReturnType<typeof layoutCanvas>>) =>
  result.nodes.map((n) => ({
    id: n.id,
    x: n.position.x,
    y: n.position.y,
    width: Number(n.style!.width),
    height: Number(n.style!.height ?? n.data.layoutHeight),
    parentId: n.parentId,
  }));
function assertNoOverlap(rects: (Rect & { id: string; parentId?: string })[]) {
  for (const [i, a] of rects.entries())
    for (const b of rects.slice(i + 1)) {
      if (a.parentId !== b.parentId) continue;
      expect(
        a.x + a.width <= b.x ||
          b.x + b.width <= a.x ||
          a.y + a.height <= b.y ||
          b.y + b.height <= a.y,
        `${a.id} overlaps ${b.id}`,
      ).toBe(true);
    }
}

describe("shared ELK research layout", () => {
  it("lays out the actual 16-node research vertically, with clear global routes", async () => {
    const p = project(
      fixture.nodes.map((n) => node(n.id, { ...n, positionSource: "auto" })),
      fixture.edges,
    );
    const before = JSON.stringify(p);
    const result = await layoutCanvas(canvas(p));
    const rects = boxes(result);
    assertNoOverlap(rects);
    const width =
      Math.max(...rects.map((n) => n.x + n.width)) -
      Math.min(...rects.map((n) => n.x));
    const height =
      Math.max(...rects.map((n) => n.y + n.height)) -
      Math.min(...rects.map((n) => n.y));
    expect(height).toBeGreaterThan(width * 1.3);
    const byId = new Map(rects.map((n) => [n.id, n]));
    for (const e of result.edges.filter((e) => !e.hidden)) {
      const route = e.data?.layoutRoute as
        { points: { x: number; y: number }[] } | undefined;
      expect(route, e.id).toBeDefined();
      expect(
        route!.points
          .slice(1)
          .every((p, i) => segmentClear(route!.points[i], p, rects)),
        e.id,
      ).toBe(true);
      if (
        (e.data?.original as { relation: string }).relation === "recorded_after"
      )
        expect(byId.get(e.target)!.y, e.id).toBeGreaterThan(
          byId.get(e.source)!.y,
        );
    }
    expect(JSON.stringify(p)).toBe(before);
    expect(result.edges.map((e) => e.id)).toEqual(p.edges.map((e) => e.id));
  });

  it("uses measured card heights without fixing natural card dimensions", async () => {
    const p = project([node("a"), node("b")], [edge("a", "b")]);
    const input = canvas(p);
    input.nodes[0].measured = { width: 368, height: 151 };
    input.nodes[1].measured = { width: 368, height: 231.5 };
    const result = await layoutCanvas(input);
    expect(result.nodes[0].data.layoutHeight).toBe(151);
    expect(result.nodes[1].data.layoutHeight).toBe(231.5);
    expect(result.nodes.every((n) => n.style!.height === undefined)).toBe(true);
    expect(result.nodes[1].position.y).toBeGreaterThanOrEqual(
      result.nodes[0].position.y + 151,
    );
  });

  it("keeps actual sibling branches parallel despite recording order", async () => {
    const p = project(
      [node("q"), node("a"), node("b")],
      [edge("q", "a"), edge("q", "b"), edge("a", "b", "recorded_after")],
    );
    const result = await layoutCanvas(canvas(p)),
      [q, a, b] = result.nodes;
    expect(a.position.y).toBe(b.position.y);
    expect(a.position.y).toBeGreaterThan(q.position.y);
    expect(a.position.x).not.toBe(b.position.x);
    expect(
      result.edges.find((e) => e.id.includes("recorded_after"))!.hidden,
    ).toBe(true);
  });

  it("stacks unattached questions without adding scientific edges", async () => {
    const p = project([node("a"), node("b"), node("c")]);
    const result = await layoutCanvas(canvas(p));
    expect(result.nodes[0].position.y).toBeLessThan(result.nodes[1].position.y);
    expect(result.nodes[1].position.y).toBeLessThan(result.nodes[2].position.y);
    expect(result.edges).toEqual([]);
  });

  it("keeps status/heartbeat changes still and is deterministic without a cached result", async () => {
    const p = project(
      [node("a"), node("b"), node("c")],
      [edge("a", "b"), edge("a", "c")],
    );
    const a = await layoutCanvas(canvas(p));
    p.nodes[0].status = "completed";
    const b = await layoutCanvas(canvas(p)),
      c = await layoutCanvas(canvas(p), { resetManual: true });
    expect(boxes(b)).toEqual(boxes(a));
    expect(boxes(c)).toEqual(boxes(a));
  });

  it("retains feedback and allocates separate ports rather than overlaid midpoint trunks", async () => {
    const p = project(
      [node("q"), node("a"), node("b")],
      [edge("q", "a"), edge("q", "b"), edge("b", "q", "revisits")],
    );
    const result = await layoutCanvas(canvas(p));
    expect(result.edges.every((e) => !!e.data?.layoutRoute)).toBe(true);
    const routes = result.edges
      .filter((e) => e.source === "q")
      .map(
        (e) =>
          (e.data!.layoutRoute as { points: { x: number; y: number }[] })
            .points[0],
      );
    expect(routes[0].x).not.toEqual(routes[1].x);
    assertNoOverlap(boxes(result));
  });

  it("preserves manual anchors and avoids automatic card collisions", async () => {
    const p = project(
      [
        node("q"),
        node("pin", { positionSource: "manual", position: { x: 100, y: 100 } }),
        node("b"),
      ],
      [edge("q", "b")],
    );
    const result = await layoutCanvas(canvas(p));
    expect(result.nodes.find((n) => n.id === "pin")!.position).toEqual({
      x: 100,
      y: 100,
    });
    assertNoOverlap(boxes(result));
    const reset = await layoutCanvas(canvas(p), { resetManual: true });
    expect(reset.nodes.find((n) => n.id === "pin")!.position).not.toEqual({
      x: 100,
      y: 100,
    });
  });

  it("retains a manually positioned descendant and reserves its enlarged frame", async () => {
    const p = project([
      node("frame", { kind: "group", position: { x: 200, y: 80 } }),
      node("pin", {
        parentId: "frame",
        positionSource: "manual",
        position: { x: 230, y: 1080 },
      }),
      node("child", { parentId: "frame" }),
      node("outside"),
    ]);
    const result = await layoutCanvas(canvas(p));
    const rects = boxes(result),
      frame = rects.find((n) => n.id === "frame")!,
      pin = rects.find((n) => n.id === "pin")!;
    expect({ x: frame.x + pin.x, y: frame.y + pin.y }).toEqual({
      x: 230,
      y: 1080,
    });
    expect(frame.height).toBeGreaterThanOrEqual(pin.y + pin.height);
    assertNoOverlap(rects);
  });

  it("explicit relayout repairs positions saved as pins by the old automatic button", async () => {
    const p = project(
      fixture.nodes.map((n) => node(n.id, n)),
      fixture.edges,
    );
    const result = await layoutCanvas(canvas(p), { resetManual: true });
    const rects = boxes(result);
    const width =
      Math.max(...rects.map((n) => n.x + n.width)) -
      Math.min(...rects.map((n) => n.x));
    const height =
      Math.max(...rects.map((n) => n.y + n.height)) -
      Math.min(...rects.map((n) => n.y));
    expect(height).toBeGreaterThan(width * 1.3);
    expect(result.edges.every((e) => !!e.data?.layoutRoute || e.hidden)).toBe(
      true,
    );
  });

  it("layouts expanded nested containers inside their frame and reflows collapsed views", async () => {
    const p = project(
      [
        node("frame", { kind: "group" }),
        node("a", { parentId: "frame" }),
        node("nested", { parentId: "frame", kind: "group" }),
        node("b", { parentId: "nested" }),
        node("outside"),
      ],
      [edge("a", "nested"), edge("b", "outside", "supports")],
    );
    const result = await layoutCanvas(canvas(p));
    const rects = boxes(result);
    assertNoOverlap(rects);
    for (const n of rects.filter((n) => n.parentId)) {
      const parent = rects.find((p) => p.id === n.parentId)!;
      expect(n.x).toBeGreaterThanOrEqual(30);
      expect(n.y).toBeGreaterThanOrEqual(100);
      expect(n.x + n.width).toBeLessThanOrEqual(parent.width);
      expect(n.y + n.height).toBeLessThanOrEqual(parent.height);
    }
    p.nodes[0].collapsed = true;
    const collapsed = await layoutCanvas(canvas(p));
    expect(collapsed.nodes.map((n) => n.id)).toEqual(["frame", "outside"]);
    expect(collapsed.edges[0].source).toBe("frame");
    expect(
      (await layoutCanvas(canvas(p, "frame"))).nodes.map((n) => n.id),
    ).toEqual(["a", "nested", "b"]);
  });
});
