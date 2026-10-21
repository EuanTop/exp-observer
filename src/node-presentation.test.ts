import { describe, expect, it } from "vitest";
import { nodePresentation } from "./node-presentation";
import { NODE_SIZE, toCanvas, type Project, type ResearchNode } from "./model";

const node: ResearchNode = {
  id: "step",
  title: "研究完成",
  kind: "finding",
  status: "completed",
  parentId: null,
  summary: "索引更新后仍与扫描结果一致。",
  notes: "",
  nextAction: "",
  tags: [],
  position: { x: 0, y: 0 },
  collapsed: false,
};
const project = (): Project => ({
  id: "research",
  name: "研究",
  description: "",
  revision: 1,
  createdAt: "",
  updatedAt: "",
  nodes: [{ ...node }],
  edges: [],
  runs: [],
  artifacts: [],
  assessments: [],
  decisions: [],
  activity: [],
});

describe("conclusions on research nodes", () => {
  it("exposes the recorded finding instead of a generic completion title", () => {
    const p = project();
    expect(nodePresentation(p, node)).toEqual({
      headline: node.summary,
      context: "研究完成",
      summary: "",
      source: "",
    });
    const canvas = toCanvas(p, null, [], { onToggle() {}, onEnter() {} });
    expect(canvas.nodes[0].data.presentation.headline).toBe(node.summary);
    expect(canvas.nodes[0].style).toMatchObject({
      width: NODE_SIZE.w,
      height: NODE_SIZE.h,
    });
  });

  it("uses explicit conclusions then the latest decision for this node", () => {
    const p = project();
    const decision = {
      id: "old",
      nodeId: node.id,
      title: "选择",
      conclusion: "旧结论",
      scope: "",
      nextAction: "",
      runIds: [],
      artifactIds: [],
    };
    p.decisions = [
      decision,
      { ...decision, id: "new", conclusion: "更新频繁时保留扫描方案。" },
      {
        ...decision,
        id: "other",
        nodeId: "other",
        conclusion: "另一个节点的结论",
      },
    ];
    expect(nodePresentation(p, node).headline).toBe("更新频繁时保留扫描方案。");
    expect(
      nodePresentation(p, { ...node, conclusion: "仅追加数据时使用索引。" }),
    ).toMatchObject({
      headline: "仅追加数据时使用索引。",
      source: "结论",
      summary: node.summary,
    });
  });

  it("ignores superseded assessments and never turns exit codes into scientific conclusions", () => {
    const p = project();
    p.runs = [
      {
        id: "r",
        nodeId: node.id,
        title: "命令",
        status: "completed",
        startedAt: null,
        configuration: {},
        metrics: { exitCode: 0, wallTimeMs: 1 },
        events: [],
        artifactIds: [],
        origin: "observed",
      },
    ];
    const assessment = {
      id: "old",
      runId: "r",
      rubric: "正确性",
      metrics: {},
      conclusion: "旧评估",
      limitations: "",
    };
    p.assessments = [
      assessment,
      {
        ...assessment,
        id: "new",
        supersedes: "old",
        conclusion: "边界输入仍有差异。",
      },
    ];
    expect(nodePresentation(p, node)).toMatchObject({
      headline: "边界输入仍有差异。",
      source: "评估 · 正确性",
    });
    p.assessments = [];
    expect(nodePresentation(p, { ...node, summary: "" })).toMatchObject({
      headline: "研究完成",
      source: "",
    });
  });

  it("keeps temporal links labelled as sequence rather than causal evidence", () => {
    const p = project();
    p.nodes.push({ ...node, id: "next", position: { x: 400, y: 0 } });
    p.edges.push({
      id: "order",
      source: node.id,
      target: "next",
      relation: "recorded_after",
    });
    expect(
      toCanvas(p, null, [], { onToggle() {}, onEnter() {} }).edges[0].label,
    ).toBe("后续记录");
  });
});
