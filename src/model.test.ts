import { describe, expect, it } from "vitest";
import {
  descendants,
  effectiveAssessments,
  toCanvas,
  validateProject,
  NODE_SIZE,
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
  it("keeps ordinary questions as cards even when they have logical children", () => {
    const question = { ...n("q"), kind: "question", collapsed: true };
    const finding = {
      ...n("f", "q"),
      kind: "finding",
      position: { x: 10, y: 350 },
    };
    const project = p([question, finding]);
    const canvas = toCanvas(project, null, [], actions);
    expect(canvas.nodes[0].data).toMatchObject({
      container: false,
      expanded: false,
      children: 1,
    });
    expect(canvas.nodes[0].style).toMatchObject({
      width: NODE_SIZE.w,
      height: NODE_SIZE.h,
    });
    expect(canvas.nodes[1].parentId).toBeUndefined();
    expect(canvas.nodes[1].position).toEqual(finding.position);
    expect(project.nodes[1].parentId).toBe("q");
  });
  it("uses only explicit containers for visual parents and preserves custom node kinds", () => {
    const group = { ...n("group"), kind: "question", isContainer: true };
    const question = { ...n("q", "group"), kind: "question" };
    const finding = { ...n("f", "q"), kind: "finding" };
    const canvas = toCanvas(p([group, question, finding]), null, [], actions);
    expect(
      canvas.nodes.find((node) => node.id === "group")?.data.expanded,
    ).toBe(true);
    expect(canvas.nodes.find((node) => node.id === "f")?.parentId).toBe(
      "group",
    );
    expect(canvas.nodes.find((node) => node.id === "q")?.data.container).toBe(
      false,
    );
    const plainGroup = toCanvas(
      p([{ ...n("a"), isContainer: false }, n("b", "a")]),
      null,
      [],
      actions,
    );
    expect(plainGroup.nodes[0].data.expanded).toBe(false);
    expect(plainGroup.nodes[1].parentId).toBeUndefined();
  });
  it("keeps capture order faint and unlabelled without inventing scientific relationships", () => {
    const project = p(
      [n("a"), n("b")],
      [
        {
          id: "order",
          source: "a",
          target: "b",
          relation: "recorded_after",
          label: "记录顺序",
          basis: "observed",
        },
      ],
    );
    const edge = toCanvas(project, null, [], actions).edges[0];
    expect(edge.label).toBe("");
    expect(edge.style?.opacity).toBeLessThan(0.5);
    expect(edge.data?.orderOnly).toBe(true);
    expect(project.edges[0].relation).toBe("recorded_after");
  });
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
  it("assigns separate reciprocal lanes after collapsing hidden endpoints", () => {
    const project = p(
      [n("a", null, true), n("child", "a"), n("b")],
      [
        { id: "out", source: "child", target: "b", relation: "supports" },
        { id: "back", source: "b", target: "child", relation: "revisits" },
      ],
    );
    const { edges } = toCanvas(project, null, [], actions);
    expect(edges.map((edge) => [edge.source, edge.target])).toEqual([
      ["a", "b"],
      ["b", "a"],
    ]);
    expect(edges[0].data?.lane).not.toBe(edges[1].data?.lane);
  });
});
