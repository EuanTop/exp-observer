import { describe, it, expect } from "vitest";
import { researchSpine } from "./research-spine";
import type { Project, ResearchNode } from "./model";
import { toCanvas } from "./model";
import { layoutCanvas } from "./graph-layout";
import fixture from "./fixtures/urban-invasion-graph.json";
const node = (
  id: string,
  critical = false,
  parentId: string | null = null,
): ResearchNode => ({
  id,
  title: id,
  kind: "finding",
  importance: critical ? "critical" : "normal",
  status: "completed",
  parentId,
  position: { x: 0, y: 0 },
  positionSource: "auto",
  summary: "",
  notes: "",
  nextAction: "",
  tags: [],
  collapsed: false,
});
const base = (nodes: ResearchNode[]): Project => ({
  id: "study",
  name: "Study",
  description: "",
  revision: 1,
  createdAt: "",
  updatedAt: "",
  nodes,
  edges: [],
  runs: [],
  artifacts: [],
  assessments: [],
  decisions: [],
  activity: [],
});
describe("research spine projection", () => {
  it("retains actual critical nodes and projects hidden paths without inventing support", () => {
    const p = base([
      node("q", true),
      node("experiment"),
      node("finding", true),
    ]);
    p.edges = [
      { id: "test", source: "q", target: "experiment", relation: "tests" },
      {
        id: "result",
        source: "experiment",
        target: "finding",
        relation: "supports",
      },
    ];
    const before = JSON.stringify(p),
      view = researchSpine(p);
    expect(view.nodes.map((n) => n.id)).toEqual(["q", "finding"]);
    expect(view.edges[0]).toMatchObject({
      relation: "collapsed_path",
      label: "经 1 个隐藏节点",
      basis: "unknown",
    });
    expect(JSON.stringify(p)).toBe(before);
  });
  it("does not turn recording order into evidence and terminates cycles", () => {
    const p = base([node("a", true), node("b"), node("c", true)]);
    p.edges = [
      { id: "1", source: "a", target: "b", relation: "recorded_after" },
      { id: "2", source: "b", target: "c", relation: "supports" },
      { id: "3", source: "b", target: "a", relation: "revisits" },
    ];
    expect(researchSpine(p).edges).toEqual([]);
    p.edges.push({
      id: "direct-order",
      source: "a",
      target: "c",
      relation: "recorded_after",
    });
    expect(researchSpine(p).edges).toEqual([]);
  });

  it("retains both branches and their convergence, without attaching an independent question", async () => {
    const p = base([
      node("q", true),
      node("test-a"),
      node("test-b"),
      node("a", true),
      node("b", true),
      node("check-a"),
      node("check-b"),
      node("answer", true),
      node("independent", true),
    ]);
    p.edges = [
      ["q", "test-a", "leads_to"],
      ["test-a", "a", "has_finding"],
      ["q", "test-b", "leads_to"],
      ["test-b", "b", "has_finding"],
      ["a", "check-a", "tests"],
      ["check-a", "answer", "summarizes"],
      ["b", "check-b", "tests"],
      ["check-b", "answer", "summarizes"],
      ["q", "independent", "recorded_after"],
    ].map(([source, target, relation]) => ({
      id: `${source}:${target}`,
      source,
      target,
      relation,
    }));
    const view = researchSpine(p);
    expect(view.edges.map((e) => [e.source, e.target])).toEqual([
      ["q", "a"],
      ["q", "b"],
      ["a", "answer"],
      ["b", "answer"],
    ]);
    expect(
      view.edges.every(
        (e) => e.relation === "collapsed_path" && e.basis === "unknown",
      ),
    ).toBe(true);
    const result = await layoutCanvas(
      toCanvas(view, null, [], { onToggle() {}, onEnter() {} }),
    );
    const positions = new Map(result.nodes.map((n) => [n.id, n.position]));
    expect(positions.get("a")!.y).toBeGreaterThan(positions.get("q")!.y);
    expect(positions.get("b")!.y).toBeGreaterThan(positions.get("q")!.y);
    expect(positions.get("answer")!.y).toBeGreaterThan(positions.get("a")!.y);
    expect(positions.get("answer")!.y).toBeGreaterThan(positions.get("b")!.y);
    expect(
      result.edges.some(
        (e) => e.source === "independent" || e.target === "independent",
      ),
    ).toBe(false);
  });

  it("preserves merging hidden branches even alongside a direct relation, with a bounded trace for cycles", () => {
    const p = base([
      node("q", true),
      node("left"),
      node("right"),
      node("merge"),
      node("answer", true),
    ]);
    p.edges = [
      ["q", "left"],
      ["q", "right"],
      ["left", "merge"],
      ["right", "merge"],
      ["merge", "left"],
      ["merge", "answer"],
    ].map(([source, target]) => ({
      id: `${source}:${target}`,
      source,
      target,
      relation: "leads_to",
    }));
    p.edges.push({
      id: "summary",
      source: "q",
      target: "answer",
      relation: "summarizes",
    });
    const before = JSON.stringify(p),
      view = researchSpine(p);
    expect(view.edges[0]).toMatchObject({
      id: "summary",
      relation: "summarizes",
    });
    expect(view.edges[1]).toMatchObject({
      source: "q",
      target: "answer",
      relation: "collapsed_path",
      spinePath: ["q:left", "left:merge", "merge:answer"],
      spineNodes: ["left", "right", "merge"],
    });
    expect(new Set(view.edges[1].spineEdges)).toEqual(
      new Set(p.edges.filter((e) => e.id !== "summary").map((e) => e.id)),
    );
    expect(JSON.stringify(p)).toBe(before);
  });

  it("does not heal missing research links in the real fixture with execution chronology", () => {
    const p = base(
      fixture.nodes.map((n) => ({
        ...node(n.id, n.kind === "finding" || n.kind === "question"),
        ...n,
      })),
    );
    p.edges = fixture.edges;
    const view = researchSpine(p);
    const kept = new Set(view.nodes.map((n) => n.id));
    expect(view.edges).toEqual(
      p.edges.filter(
        (e) =>
          e.relation !== "recorded_after" &&
          kept.has(e.source) &&
          kept.has(e.target),
      ),
    );
    expect(view.edges.some((e) => e.spinePath)).toBe(false);
    const roots = view.nodes.filter(
      (n) =>
        n.kind === "question" && !view.edges.some((e) => e.target === n.id),
    );
    expect(roots).toHaveLength(3);
  });
  it("keeps containers but omits ordinary logical parents", () => {
    const p = base([
      { ...node("frame"), kind: "group" },
      node("parent", false, "frame"),
      node("important", true, "parent"),
    ]);
    const view = researchSpine(p);
    expect(view.nodes.map((n) => n.id)).toEqual(["frame", "important"]);
    expect(view.nodes[1].parentId).toBe("frame");
  });
});
