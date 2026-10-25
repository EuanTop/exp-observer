import { describe, expect, it } from "vitest";
import { layoutCanvas, type Canvas, type LayoutRoute } from "./graph-layout";
import { toCanvas, type Project, type ResearchNode } from "./model";
import { segmentClear } from "./edge-routing";

const node = (id: string, patch: Partial<ResearchNode> = {}): ResearchNode => ({
  id,
  title: id,
  kind: "question",
  status: "paused",
  parentId: null,
  summary: "",
  notes: "",
  nextAction: "",
  tags: [],
  position: { x: 40, y: 40 },
  positionSource: "auto",
  collapsed: true,
  ...patch,
});
const edge = (source: string, target: string, relation = "supports") => ({
  id: `${source}:${target}`,
  source,
  target,
  relation,
});
const study = (branches = 2): Project => ({
  id: "parallel",
  name: "Actual fork and synthesis structure",
  description: "",
  revision: 1,
  createdAt: "",
  updatedAt: "",
  activity: [],
  nodes: [
    node("question"),
    ...Array.from({ length: branches }, (_, i) => node(`branch${i}`)),
    node("finding", { kind: "finding", status: "completed" }),
  ],
  edges: [
    edge("question", "finding", "has_finding"),
    ...Array.from({ length: branches }, (_, i) =>
      edge("question", `branch${i}`, "branches"),
    ),
    ...Array.from({ length: branches }, (_, i) =>
      edge(`branch${i}`, "finding", "summarizes"),
    ),
  ],
  runs: [],
  artifacts: [],
  assessments: [],
  decisions: [],
  usageRecords: [],
});
const canvas = (p: Project, expandedIds = new Set<string>()) =>
  toCanvas(p, null, [], { onToggle() {}, onEnter() {} }, { expandedIds });
const bounds = (c: Canvas) =>
  c.nodes.map((n) => ({
    id: n.id,
    x: n.position.x,
    y: n.position.y,
    width: Number(n.style!.width),
    height: Number(n.data.layoutHeight),
  }));
function assertAxis(c: Canvas) {
  const rects = bounds(c),
    q = rects.find((n) => n.id === "question")!,
    f = rects.find((n) => n.id === "finding")!,
    middle = q.x + q.width / 2;
  expect(f.x + f.width / 2).toBeCloseTo(middle, 1);
  const route = c.edges.find((e) => e.id === "question:finding")!.data!
    .layoutRoute as LayoutRoute;
  expect(route.points).toHaveLength(2);
  expect(route.points[0].x).toBeCloseTo(middle, 1);
  expect(route.points[1].x).toBeCloseTo(middle, 1);
  for (const e of c.edges) {
    const r = e.data?.layoutRoute as LayoutRoute;
    expect(r, e.id).toBeDefined();
    expect(
      r.points.slice(1).every((p, i) => segmentClear(r.points[i], p, rects)),
      e.id,
    ).toBe(true);
  }
  const branches = rects.filter((n) => n.id.startsWith("branch"));
  expect(branches.some((n) => n.x + n.width < middle)).toBe(true);
  expect(branches.some((n) => n.x > middle)).toBe(true);
  return branches;
}

describe("centered parallel research paths", () => {
  it("centers the actual four-card structure and top-aligns unequal branch cards", async () => {
    const p = study(),
      before = JSON.stringify(p),
      c = canvas(p);
    c.nodes.forEach((n, i) => {
      n.measured = { width: 368, height: [216, 250, 304, 238][i] };
    });
    const result = await layoutCanvas(c),
      branches = assertAxis(result);
    expect(branches[0].y).toBe(branches[1].y);
    for (const e of result.edges.filter((e) => e.id !== "question:finding"))
      expect(
        (e.data!.layoutRoute as LayoutRoute).points.length,
      ).toBeGreaterThan(2);
    expect(JSON.stringify(p)).toBe(before);
  });

  it("retains a central corridor with an odd number of independent branches", async () => {
    assertAxis(await layoutCanvas(canvas(study(3))));
  });

  it("keeps the axis when parallel paths contain several experiment steps", async () => {
    const p = study();
    p.nodes.splice(2, 0, node("step"));
    p.edges = p.edges.filter((e) => e.id !== "branch0:finding");
    p.edges.push(edge("branch0", "step"), edge("step", "finding"));
    assertAxis(await layoutCanvas(canvas(p)));
  });

  it("applies the same structure inside an expanded container", async () => {
    const p = study();
    p.nodes.forEach((n) => {
      n.parentId = "frame";
    });
    p.nodes.unshift(node("frame", { isContainer: true }));
    const c = await layoutCanvas(canvas(p, new Set(["frame"])));
    const q = c.nodes.find((n) => n.id === "question")!,
      f = c.nodes.find((n) => n.id === "finding")!;
    expect(q.position.x).toBeCloseTo(f.position.x, 1);
    const route = c.edges.find((e) => e.id === "question:finding")!.data!
      .layoutRoute as LayoutRoute;
    const frame = c.nodes.find((n) => n.id === "frame")!;
    expect(route.points).toHaveLength(2);
    expect(route.points[0].x).toBeCloseTo(
      frame.position.x + q.position.x + Number(q.style!.width) / 2,
      1,
    );
    expect(route.points[1].x).toBeCloseTo(route.points[0].x, 1);
  });

  it("honors manual anchors until the user explicitly requests automatic layout", async () => {
    const p = study();
    Object.assign(p.nodes[1], {
      positionSource: "manual",
      position: { x: 100, y: 600 },
    });
    expect((await layoutCanvas(canvas(p))).nodes[1].position).toEqual({
      x: 100,
      y: 600,
    });
    assertAxis(await layoutCanvas(canvas(p), { resetManual: true }));
  });

  it("preserves an extra entry and its route instead of forcing an ambiguous region", async () => {
    const p = study();
    p.nodes.unshift(node("other"));
    p.edges.push(edge("other", "branch0"));
    const c = await layoutCanvas(canvas(p));
    expect(c.edges.map((e) => e.id)).toEqual(p.edges.map((e) => e.id));
    const rects = bounds(c);
    for (const e of c.edges) {
      const r = e.data!.layoutRoute as LayoutRoute;
      expect(
        r.points.slice(1).every((p, i) => segmentClear(r.points[i], p, rects)),
        e.id,
      ).toBe(true);
    }
  });
});
