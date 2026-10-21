import { describe, expect, it } from "vitest";
import {
  descendants,
  effectiveAssessments,
  toCanvas,
  validateProject,
  type Project,
  type ResearchNode,
} from "./model";
const n = (
  id: string,
  parentId: string | null = null,
  collapsed = false,
): ResearchNode => ({
  id,
  title: id,
  kind: "group",
  status: "active",
  parentId,
  summary: "",
  notes: "",
  nextAction: "",
  tags: [],
  position: { x: 10, y: 10 },
  collapsed,
});
const p = (nodes: ResearchNode[], edges: any[] = []): Project => ({
  id: "p",
  name: "p",
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
const actions = { onToggle: () => {}, onEnter: () => {} };
describe("nested research graph", () => {
  it("folds descendants while preserving cross-boundary relationships", () => {
    const project = p(
      [n("a", null, true), n("b", "a"), n("c", "b"), n("d")],
      [{ id: "e", source: "c", target: "d", relation: "supports" }],
    );
    const canvas = toCanvas(project, null, [], actions);
    expect(canvas.nodes.map((n) => n.id)).toEqual(["a", "d"]);
    expect(canvas.edges[0].source).toBe("a");
    expect(canvas.edges[0].target).toBe("d");
  });
  it("shows descendants when entering a collapsed container", () => {
    const project = p([n("a", null, true), n("b", "a"), n("c", "b")]);
    expect(toCanvas(project, "a", [], actions).nodes.map((n) => n.id)).toEqual([
      "b",
      "c",
    ]);
  });
  it("keeps arbitrary containment independent of semantic cycles", () => {
    const project = p(
      [n("a"), n("b", "a"), n("c", "b")],
      [
        { id: "ab", source: "a", target: "c", relation: "tests" },
        { id: "ca", source: "c", target: "a", relation: "revisits" },
      ],
    );
    expect(validateProject(project)).toEqual([]);
    expect(descendants(project.nodes, "a")).toEqual(["b", "c"]);
  });
  it("rejects containment cycles", () => {
    expect(
      validateProject(p([n("a", "b"), n("b", "a")])).length,
    ).toBeGreaterThan(0);
  });
  it("does not count re-evaluation as a new execution", () => {
    const project = p([]);
    project.assessments = [
      {
        id: "v1",
        runId: "r",
        rubric: "q",
        metrics: {},
        conclusion: "",
        limitations: "",
      },
      {
        id: "v2",
        runId: "r",
        rubric: "q",
        metrics: {},
        conclusion: "",
        limitations: "",
        supersedes: "v1",
      },
    ];
    expect(effectiveAssessments(project).map((a) => a.id)).toEqual(["v2"]);
    expect(project.runs).toHaveLength(0);
  });
});
