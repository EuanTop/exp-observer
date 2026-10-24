import { describe, it, expect } from "vitest";
import {
  toCanvas,
  boundaryRelations,
  type Project,
  type ResearchNode,
} from "./model";
import { layoutCanvas } from "./graph-layout";
import { ResearchCard } from "./components/ResearchCard";
import { BoundaryInspector } from "./components/BoundaryInspector";
import { ReactFlowProvider } from "@xyflow/react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const node = (
  id: string,
  parentId: string | null = null,
  extra: Partial<ResearchNode> = {},
): ResearchNode => ({
  id,
  title: id,
  parentId,
  kind: "question",
  status: "completed",
  summary: "",
  notes: "",
  nextAction: "",
  tags: [],
  position: { x: 40, y: 40 },
  positionSource: "auto",
  collapsed: false,
  ...extra,
});
const project = (): Project => ({
  id: "p",
  name: "Study",
  description: "",
  revision: 1,
  createdAt: "",
  updatedAt: "",
  activity: [],
  nodes: [
    node("main"),
    node("branch-a"),
    node("a1", "branch-a", { kind: "finding", conclusion: "Observed result" }),
    node("nested", "branch-a"),
    node("n1", "nested", { kind: "experiment" }),
    node("branch-b"),
    node("b1", "branch-b", { kind: "finding" }),
    node("answer", null, { kind: "finding" }),
  ],
  edges: [
    { id: "start-a", source: "main", target: "branch-a", relation: "branches" },
    { id: "start-b", source: "main", target: "branch-b", relation: "branches" },
    { id: "internal", source: "a1", target: "nested", relation: "motivates" },
    {
      id: "proof1",
      source: "a1",
      target: "answer",
      relation: "supports",
      basis: "observed",
    },
    {
      id: "proof2",
      source: "n1",
      target: "answer",
      relation: "supports",
      basis: "observed",
    },
    { id: "proof3", source: "b1", target: "answer", relation: "summarizes" },
    {
      id: "feedback",
      source: "answer",
      target: "n1",
      relation: "revisits",
      basis: "hypothesis",
    },
  ],
  runs: [],
  artifacts: [],
  assessments: [],
  decisions: [],
  usageRecords: [],
  runtimeActivity: [],
});
const actions = { onToggle() {}, onEnter() {} };

describe("hierarchical research workspace", () => {
  it("makes the main story the outer level, independently of legacy importance or collapse flags", () => {
    const p = project(),
      before = JSON.stringify(p);
    p.nodes[2].importance = "critical";
    const c = toCanvas(p, null, [], actions);
    expect(c.nodes.map((n) => n.id)).toEqual([
      "main",
      "branch-a",
      "branch-b",
      "answer",
    ]);
    expect(c.nodes.every((n) => !n.data.expanded)).toBe(true);
    p.nodes[2].importance = undefined;
    expect(JSON.stringify(p)).toBe(before);
  });
  it("enters one level without exposing grandchildren and can enter a deeper question", () => {
    const p = project();
    expect(toCanvas(p, "branch-a", [], actions).nodes.map((n) => n.id)).toEqual(
      ["a1", "nested"],
    );
    expect(toCanvas(p, "nested", [], actions).nodes.map((n) => n.id)).toEqual([
      "n1",
    ]);
    const inline = toCanvas(p, null, [], actions, {
      expandedIds: new Set(["branch-a"]),
    });
    expect(inline.nodes.find((n) => n.id === "nested")?.data.expanded).toBe(
      false,
    );
    expect(inline.nodes.some((n) => n.id === "n1")).toBe(false);
    expect(inline.nodes.find((n) => n.id === "nested")?.parentId).toBe(
      "branch-a",
    );
  });
  it("aggregates boundary links without losing original proof, directions or hypotheses", () => {
    const c = toCanvas(project(), null, [], actions);
    const proof = c.edges.find(
      (e) => e.source === "branch-a" && e.target === "answer",
    )!;
    expect(
      (proof.data?.originals as Project["edges"]).map((e) => e.id),
    ).toEqual(["proof1", "proof2"]);
    expect(proof.data?.boundary).toBe(true);
    expect(proof.label).toContain("2");
    const feedback = c.edges.find(
      (e) => e.source === "answer" && e.target === "branch-a",
    )!;
    expect(feedback.data?.original).toMatchObject({
      source: "answer",
      target: "n1",
      basis: "hypothesis",
    });
    expect(feedback.style?.strokeDasharray).toBeTruthy();
    expect(c.edges.some((e) => e.id === "internal")).toBe(false);
    expect(
      toCanvas(project(), "branch-a", [], actions).edges.map((e) => e.id),
    ).toContain("internal");
  });
  it("bundles mixed boundary meanings without claiming that every link is support", () => {
    const p = project();
    p.edges.push({
      id: "summary",
      source: "branch-a",
      target: "answer",
      relation: "summarizes",
      basis: "hypothesis",
    });
    const c = toCanvas(p, null, [], actions),
      matches = c.edges.filter(
        (e) => e.source === "branch-a" && e.target === "answer",
      );
    expect(matches).toHaveLength(1);
    expect(matches[0].label).toBe("关联 · 3");
    expect(matches[0].data?.originals).toHaveLength(3);
    expect(p.edges.at(-1)?.basis).toBe("hypothesis");
  });
  it("keeps cross-level references inspectable while excluding unrelated branches", () => {
    const p = project(),
      edges = boundaryRelations(p, "branch-a");
    expect(edges.map((e) => e.id)).toEqual([
      "start-a",
      "proof1",
      "proof2",
      "feedback",
    ]);
    const html = renderToStaticMarkup(
      createElement(BoundaryInspector, {
        project: p,
        edges,
        onSelect() {},
        onEdit() {},
        onClose() {},
      }),
    );
    expect(html).toContain("branch-a / nested / n1");
    expect(html).toContain("查看原始关系");
    expect(html).not.toContain("proof3");
  });
  it("does not turn cross-container capture order into a research connection", () => {
    const p = project();
    p.edges.push({
      id: "chronology",
      source: "n1",
      target: "b1",
      relation: "recorded_after",
    });
    expect(
      toCanvas(p, null, [], actions).edges.some(
        (e) => (e.data?.original as any)?.id === "chronology",
      ),
    ).toBe(false);
    expect(p.edges.at(-1)?.relation).toBe("recorded_after");
  });
  it("propagates measured live activity through owners without changing their disposition", () => {
    const p = project();
    p.nodes[1].status = "paused";
    p.runtimeActivity = [
      { id: "live", nodeId: "n1", source: "local-executor" },
    ];
    expect(
      toCanvas(p, null, [], actions).nodes.find((n) => n.id === "branch-a")
        ?.data.processing,
    ).toBe(true);
    expect(p.nodes[1].status).toBe("paused");
    const data = toCanvas(p, null, [], actions).nodes.find(
      (n) => n.id === "branch-a",
    )!.data;
    const html = renderToStaticMarkup(
      createElement(
        ReactFlowProvider,
        null,
        createElement(ResearchCard, { data, selected: false } as Parameters<
          typeof ResearchCard
        >[0]),
      ),
    );
    expect(html).toContain("status-paused");
    expect(html).toContain("内部执行中");
    expect(html).not.toContain("status-running");
    p.runtimeActivity = [];
    expect(
      toCanvas(p, null, [], actions).nodes.find((n) => n.id === "branch-a")
        ?.data.processing,
    ).toBe(false);
  });
  it("aggregates descendant usage once and never traverses semantic connections", () => {
    const p = project();
    p.usageRecords = [
      {
        id: "native1",
        nodeId: "n1",
        source: "codex",
        sourceRef: "response1",
        provider: "openai",
        model: "actual",
        inputTokens: 100,
        outputTokens: 20,
        cacheReadTokens: 50,
        cacheWriteTokens: 0,
        startedAt: null,
        finishedAt: null,
      },
    ];
    const c = toCanvas(p, null, [], actions);
    expect(
      c.nodes.find((n) => n.id === "branch-a")?.data.usage?.totalTokens,
    ).toBe(120);
    expect(
      c.nodes.find((n) => n.id === "answer")?.data.usage?.totalTokens,
    ).toBeNull();
    expect(
      toCanvas(p, "branch-a", [], actions).nodes.find((n) => n.id === "nested")
        ?.data.usage?.totalTokens,
    ).toBe(120);
  });
  it("shows a recorded latest finding and real navigation, with no separate critical badge", () => {
    const p = project();
    p.nodes[1].importance = "critical";
    const data = toCanvas(p, null, [], actions).nodes.find(
      (n) => n.id === "branch-a",
    )!.data;
    expect(data.presentation).toMatchObject({
      headline: "branch-a",
      conclusion: "Observed result",
      source: "最近发现",
    });
    const html = renderToStaticMarkup(
      createElement(
        ReactFlowProvider,
        null,
        createElement(ResearchCard, { data, selected: false } as Parameters<
          typeof ResearchCard
        >[0]),
      ),
    );
    expect(html).toContain("进入 ·");
    expect(html).toContain("就地展开容器");
    expect(html).not.toContain("is-critical");
    expect(html).not.toContain("关键");
  });
  it("retains top-down flow and branch convergence at both overview and entered levels", async () => {
    const p = project(),
      root = await layoutCanvas(toCanvas(p, null, [], actions));
    const y = (id: string) => root.nodes.find((n) => n.id === id)!.position.y;
    expect(y("main")).toBeLessThan(y("branch-a"));
    expect(y("main")).toBeLessThan(y("branch-b"));
    expect(y("branch-a")).toBeLessThan(y("answer"));
    const nested = await layoutCanvas(toCanvas(p, "branch-a", [], actions));
    expect(nested.nodes.find((n) => n.id === "a1")!.position.y).toBeLessThan(
      nested.nodes.find((n) => n.id === "nested")!.position.y,
    );
  });
});
