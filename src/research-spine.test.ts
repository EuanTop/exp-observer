import { describe, it, expect } from "vitest";
import { researchSpine } from "./research-spine";
import type { Project, ResearchNode } from "./model";
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
