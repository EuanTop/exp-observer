import { beforeEach, describe, expect, it } from "vitest";
import { setLocale } from "./i18n";

beforeEach(() => setLocale("zh-CN"));
import { isNodeProcessing, nodePresentation } from "./node-presentation";
import { NODE_SIZE, toCanvas, type Project, type ResearchNode } from "./model";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ReactFlowProvider } from "@xyflow/react";
import { ResearchCard } from "./components/ResearchCard";
import { estimateCardHeight } from "./card-sizing";

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
  it("prioritizes the recorded pause reason and recovery condition without changing the question", () => {
    const paused = {
      ...node,
      status: "paused",
      pauseReason: "当前样本不足以确认稳定效应。",
      resumeWhen: "取得独立样地数据后验证。",
      nextAction: "准备独立样地。",
    };
    const p = project(),
      presentation = nodePresentation(p, paused);
    expect(presentation).toMatchObject({
      headline: node.title,
      pauseReason: paused.pauseReason,
      resumeWhen: paused.resumeWhen,
      summary: node.summary,
    });
    expect(presentation.nextAction).toBeUndefined();
    expect(estimateCardHeight(presentation)).toBeGreaterThan(
      estimateCardHeight(nodePresentation(p, node)),
    );
    const data = toCanvas({ ...p, nodes: [paused] }, null, [], {
      onToggle() {},
      onEnter() {},
    }).nodes[0].data;
    const html = renderToStaticMarkup(
      createElement(
        ReactFlowProvider,
        null,
        createElement(ResearchCard, { data, selected: false } as Parameters<
          typeof ResearchCard
        >[0]),
      ),
    );
    expect(html).toContain("state-paused");
    expect(html).toContain(node.title);
    expect(html).toContain("恢复：");
    expect(html.indexOf(paused.pauseReason)).toBeLessThan(
      html.indexOf(node.summary),
    );
    expect(html.indexOf(paused.resumeWhen)).toBeLessThan(
      html.indexOf(node.summary),
    );
    expect(html).toContain('title="查看平台捕获的命令执行"');
    expect(html).toContain('title="查看步骤计时与执行耗时"');
    expect(html).toContain("未采集执行");
  });

  it("uses a recorded next action only when no recovery condition exists and never invents pause text", () => {
    const paused = {
      ...node,
      status: "paused",
      summary: "",
      nextAction: "收集独立样地。",
    };
    expect(nodePresentation(project(), paused)).toMatchObject({
      headline: node.title,
      nextAction: paused.nextAction,
      summary: "",
    });
    expect(
      nodePresentation(project(), { ...paused, nextAction: "" }).pauseReason,
    ).toBeUndefined();
    expect(
      nodePresentation(project(), {
        ...paused,
        status: "completed",
        pauseReason: "旧暂停原因",
      }).pauseReason,
    ).toBeUndefined();
  });

  it("renders failure feedback while an open question alone never gains a processing outline", () => {
    const render = (status: string) => {
      const p = { ...project(), nodes: [{ ...node, status }] };
      const data = toCanvas(p, null, [], { onToggle() {}, onEnter() {} })
        .nodes[0].data;
      return renderToStaticMarkup(
        createElement(
          ReactFlowProvider,
          null,
          createElement(ResearchCard, { data, selected: false } as Parameters<
            typeof ResearchCard
          >[0]),
        ),
      );
    };
    expect(render("failed")).toContain("state-failed");
    expect(render("failed")).toContain("status-failed");
    expect(render("active")).not.toContain("processing-outline");
    expect(render("completed")).toContain('stroke="#fff"');
  });

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
      height: expect.any(Number),
    });
  });

  it("previews retained notes without inventing text, and leaves empty work compact", () => {
    const p = project();
    const finding = {
      ...node,
      summary: "",
      notes: "第一段原始分析。\n\n第二段详细计算。",
    };
    expect(nodePresentation(p, finding).summary).toBe("第一段原始分析。");
    expect(
      nodePresentation(p, { ...finding, conclusion: finding.title }).summary,
    ).toBe("第一段原始分析。");
    const empty = { ...node, title: "运行样地模型", summary: "", notes: "" };
    const a = toCanvas({ ...p, nodes: [empty] }, null, [], {
      onToggle() {},
      onEnter() {},
    }).nodes[0];
    const b = toCanvas({ ...p, nodes: [finding] }, null, [], {
      onToggle() {},
      onEnter() {},
    }).nodes[0];
    expect(Number(a.style!.height)).toBeLessThan(Number(b.style!.height));
    expect(Number(a.style!.height)).toBeLessThan(160);
    expect(
      nodePresentation(p, { ...empty, nextAction: "取得独立样地后复测" })
        .summary,
    ).toBe("取得独立样地后复测");
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

  it("keeps temporal links as faint sequence without a competing causal label", () => {
    const p = project();
    p.nodes.push({ ...node, id: "next", position: { x: 400, y: 0 } });
    p.edges.push({
      id: "order",
      source: node.id,
      target: "next",
      relation: "recorded_after",
    });
    const edge = toCanvas(p, null, [], { onToggle() {}, onEnter() {} })
      .edges[0];
    expect(edge.label).toBe("");
    expect(edge.data?.orderOnly).toBe(true);
    expect(p.edges[0].relation).toBe("recorded_after");
  });
});

describe("recorded node processing state", () => {
  it("does not infer execution from an open question, a node status or selection", () => {
    const p = project();
    expect(isNodeProcessing(p, node)).toBe(false);
    expect(isNodeProcessing(p, { ...node, status: "active" })).toBe(false);
    expect(isNodeProcessing(p, { ...node, status: "running" })).toBe(false);
    const canvas = toCanvas(p, null, [node.id], {
      onToggle() {},
      onEnter() {},
    });
    expect(canvas.nodes[0].selected).toBe(true);
    expect(canvas.nodes[0].data.processing).toBe(false);
  });

  it("prioritizes live executor snapshots over stale run records, without changing research state", () => {
    const p = project();
    p.runs = [
      {
        id: "old",
        nodeId: node.id,
        status: "running",
      } as Project["runs"][number],
    ];
    p.runtimeActivity = [];
    expect(isNodeProcessing(p, node)).toBe(false);
    p.runtimeActivity.push({
      id: "capture",
      nodeId: node.id,
      source: "local-executor",
    });
    expect(isNodeProcessing(p, node)).toBe(true);
    expect(node.status).toBe("completed");
    p.runtimeActivity = [];
    expect(isNodeProcessing(p, node)).toBe(false);
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
    p.runs[0].nodeId = node.id;
    p.runs[0].finishedAt = "2026-01-01T00:00:01Z";
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
