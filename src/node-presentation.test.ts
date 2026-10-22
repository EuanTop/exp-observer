import { describe, expect, it } from "vitest";
import { isNodeProcessing, nodePresentation } from "./node-presentation";
import { NODE_SIZE, toCanvas, type Project, type ResearchNode } from "./model";

const node: ResearchNode = {
  id: "step",
  title: "追加更新会改变输出吗？",
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

describe("research card content", () => {
  it("keeps the research question as title and recorded context/finding in the body", () => {
    const p = project();
    expect(nodePresentation(p, node)).toEqual({
      headline: node.title,
      context: "",
      summary: node.summary,
      conclusion: "",
      source: "",
    });
    const canvas = toCanvas(p, null, [], { onToggle() {}, onEnter() {} });
    expect(canvas.nodes[0].data.presentation.headline).toBe(node.title);
    expect(canvas.nodes[0].data.presentation.summary).toBe(node.summary);
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
    expect(nodePresentation(p, node)).toMatchObject({
      headline: node.title,
      conclusion: "更新频繁时保留扫描方案。",
    });
    expect(
      nodePresentation(p, { ...node, conclusion: "仅追加数据时使用索引。" }),
    ).toMatchObject({
      headline: node.title,
      conclusion: "仅追加数据时使用索引。",
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
      headline: node.title,
      conclusion: "边界输入仍有差异。",
      source: "评估 · 正确性",
    });
    p.assessments = [];
    expect(nodePresentation(p, { ...node, summary: "" })).toMatchObject({
      headline: node.title,
      conclusion: "",
      summary: "",
      source: "",
    });
  });

  it("omits repeated conclusions and tolerates absent optional text/history", () => {
    expect(
      nodePresentation(project(), { ...node, conclusion: node.summary }),
    ).toMatchObject({ summary: node.summary, conclusion: "", source: "" });
    expect(
      nodePresentation(project(), { ...node, conclusion: node.title }),
    ).toMatchObject({ headline: node.title, conclusion: "" });
    expect(
      nodePresentation(
        {} as Project,
        { id: "empty", title: "" } as ResearchNode,
      ),
    ).toMatchObject({ headline: "未命名节点", summary: "", conclusion: "" });
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

describe("recorded node processing state", () => {
  it("lights active/running nodes, but never a completed node merely because it is selected", () => {
    const p = project();
    expect(isNodeProcessing(p, node)).toBe(false);
    expect(isNodeProcessing(p, { ...node, status: "active" })).toBe(true);
    expect(isNodeProcessing(p, { ...node, status: "running" })).toBe(true);
    const canvas = toCanvas(p, null, [node.id], {
      onToggle() {},
      onEnter() {},
    });
    expect(canvas.nodes[0].selected).toBe(true);
    expect(canvas.nodes[0].data.processing).toBe(false);
  });

  it("uses any running run on this node, even when a more recent run finished", () => {
    const p = project();
    const run = {
      id: "running",
      nodeId: node.id,
      title: "测量",
      status: "running",
      configuration: {},
      metrics: {},
      startedAt: null,
      events: [],
      artifactIds: [],
      origin: "observed",
    };
    p.runs = [run, { ...run, id: "done", status: "completed" }];
    expect(isNodeProcessing(p, node)).toBe(true);
    p.runs[0].nodeId = "other";
    expect(isNodeProcessing(p, node)).toBe(false);
  });

  it("uses ongoing observations and stops when they finish, without inferring activity from usage totals", () => {
    const p = project();
    p.observations = [
      {
        id: "step",
        nodeId: node.id,
        title: "检查",
        status: "running",
        startedAt: "2026-01-01T00:00:00Z",
        finishedAt: null,
        durationMs: null,
        inputTokens: 40,
        outputTokens: 20,
        usageSource: "test",
        origin: "observed",
      },
    ];
    expect(isNodeProcessing(p, node)).toBe(true);
    p.observations[0].finishedAt = "2026-01-01T00:00:01Z";
    expect(isNodeProcessing(p, node)).toBe(false);
    p.observations[0].status = "finished";
    expect(isNodeProcessing(p, node)).toBe(false);
    expect(isNodeProcessing({} as Project, node)).toBe(false);
  });
});
