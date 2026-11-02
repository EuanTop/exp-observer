import { describe, expect, it, vi } from "vitest";
import * as usageModule from "./usage";
import { buildResearchRows, tableTime } from "./research-table";
import { getNodeUsage } from "./usage";
import type { Project, ResearchNode, Run } from "./model";

const node = (
  id: string,
  parentId: string | null = null,
  extra: Partial<ResearchNode> = {},
): ResearchNode => ({
  id,
  parentId,
  title: id,
  kind: "question",
  status: "active",
  summary: "",
  notes: "",
  nextAction: "",
  tags: [],
  position: { x: 0, y: 0 },
  collapsed: false,
  ...extra,
});
const project = (): Project => ({
  id: "study",
  name: "Study",
  description: "",
  revision: 1,
  createdAt: "",
  updatedAt: "",
  nodes: [
    node("goal"),
    node("branch", "goal"),
    node("finding", "branch", {
      kind: "finding",
      status: "completed",
      conclusion: "Learned something",
    }),
    node("parallel", "goal", { kind: "custom-method", status: "paused" }),
    node("answer", null, { kind: "finding" }),
  ],
  edges: [
    {
      id: "support",
      source: "finding",
      target: "answer",
      relation: "supports",
    },
  ],
  runs: [],
  artifacts: [],
  assessments: [],
  decisions: [],
  activity: [],
});
const execution = (id: string, nodeId: string, ms: number): Run => ({
  id,
  nodeId,
  title: id,
  status: "completed",
  configuration: {},
  metrics: { wallTimeMs: ms },
  startedAt: null,
  events: [],
  artifactIds: [],
  origin: "observed",
});
const view = (p: Project, expandedIds = new Set<string>()) =>
  buildResearchRows(p, { expandedIds });

describe("research tree table", () => {
  it("shows the outer main story by default and expands explicit nesting without duplicating semantic neighbours", () => {
    const p = project();
    expect(view(p).map((row) => row.node.id)).toEqual(["goal", "answer"]);
    expect(view(p)[0]).toMatchObject({
      depth: 0,
      hasChildren: true,
      childCount: 2,
      expanded: false,
      contextOnly: false,
    });
    const rows = view(p, new Set(["goal", "branch"]));
    expect(rows.map((row) => [row.node.id, row.depth])).toEqual([
      ["goal", 0],
      ["branch", 1],
      ["finding", 2],
      ["parallel", 1],
      ["answer", 0],
    ]);
    expect(new Set(rows.map((row) => row.node.id)).size).toBe(5);
  });

  it("reveals only matching paths and retains their ancestors as context without changing expansion", () => {
    const p = project(),
      expandedIds = new Set<string>();
    const rows = buildResearchRows(p, {
      expandedIds,
      query: "learned something",
    });
    expect(
      rows.map((row) => [row.node.id, row.contextOnly, row.expanded]),
    ).toEqual([
      ["goal", true, true],
      ["branch", true, true],
      ["finding", false, false],
    ]);
    expect(expandedIds.size).toBe(0);
    expect(
      buildResearchRows(p, { expandedIds, query: "goal" }).map(
        (row) => row.node.id,
      ),
    ).toEqual(["goal"]);
    expect(
      buildResearchRows(p, { expandedIds, query: "not in this research" }),
    ).toEqual([]);
  });

  it("combines state, custom type and search filters while preserving source paths", () => {
    const p = project();
    p.nodes[3].notes = "A suspended avenue";
    const rows = buildResearchRows(p, {
      expandedIds: new Set(),
      query: "SUSPENDED",
      status: "paused",
      kind: "custom-method",
    });
    expect(rows.map((row) => row.node.id)).toEqual(["goal", "parallel"]);
    expect(rows[1].contextOnly).toBe(false);
    expect(
      buildResearchRows(p, {
        expandedIds: new Set(),
        query: "  ",
        status: "all",
        kind: "all",
      }).map((row) => row.node.id),
    ).toEqual(["goal", "answer"]);
  });

  it("sorts siblings without pulling descendants away from their parent and keeps equal values stable", () => {
    const p = project();
    p.nodes[1].title = "Z branch";
    p.nodes[3].title = "A branch";
    const rows = buildResearchRows(p, {
      expandedIds: new Set(["goal", "branch"]),
      sort: "title",
    });
    expect(rows.map((row) => row.node.id)).toEqual([
      "answer",
      "goal",
      "parallel",
      "branch",
      "finding",
    ]);
    p.nodes[1].title = p.nodes[3].title = "Same";
    expect(
      buildResearchRows(p, {
        expandedIds: new Set(["goal"]),
        sort: "title",
        direction: "desc",
      })
        .filter((row) => row.depth === 1)
        .map((row) => row.node.id),
    ).toEqual(["branch", "parallel"]);
    expect(
      buildResearchRows(p, {
        expandedIds: new Set(),
        sort: "recorded",
        direction: "desc",
      }).map((row) => row.node.id),
    ).toEqual(["answer", "goal"]);
  });

  it("sorts known time/token values including zero ahead of unknown in either direction and uses graph rollups", () => {
    const p = project();
    p.nodes = [
      node("unknown"),
      node("slow"),
      node("zero"),
      node("fast"),
      node("nested", "slow"),
    ];
    p.runs = [
      execution("slow-run", "slow", 10),
      execution("nested-run", "nested", 30),
      execution("zero-run", "zero", 0),
      execution("fast-run", "fast", 4),
    ];
    p.runs.push({ ...p.runs[1] });
    p.usageRecords = [
      {
        id: "u1",
        nodeId: "nested",
        source: "codex",
        sourceRef: "turn",
        provider: "openai",
        model: "m",
        inputTokens: 5,
        outputTokens: 2,
        cacheReadTokens: null,
        cacheWriteTokens: null,
        startedAt: null,
        finishedAt: null,
      },
      {
        id: "u1-copy",
        nodeId: "nested",
        source: "codex",
        sourceRef: "turn",
        provider: "openai",
        model: "m",
        inputTokens: 5,
        outputTokens: 2,
        cacheReadTokens: null,
        cacheWriteTokens: null,
        startedAt: null,
        finishedAt: null,
      },
      {
        id: "u2",
        nodeId: "zero",
        source: "codex",
        sourceRef: "turn2",
        provider: "openai",
        model: "m",
        inputTokens: 0,
        outputTokens: 0,
        cacheReadTokens: null,
        cacheWriteTokens: null,
        startedAt: null,
        finishedAt: null,
      },
      {
        id: "u3",
        nodeId: "fast",
        source: "codex",
        sourceRef: "turn3",
        provider: "openai",
        model: "m",
        inputTokens: 3,
        outputTokens: 0,
        cacheReadTokens: null,
        cacheWriteTokens: null,
        startedAt: null,
        finishedAt: null,
      },
    ];
    for (const sort of ["time", "tokens"] as const) {
      expect(
        buildResearchRows(p, { expandedIds: new Set(), sort }).map(
          (row) => row.node.id,
        ),
      ).toEqual(["zero", "fast", "slow", "unknown"]);
      const rows = buildResearchRows(p, {
        expandedIds: new Set(),
        sort,
        direction: "desc",
      });
      expect(rows.map((row) => row.node.id)).toEqual([
        "slow",
        "fast",
        "zero",
        "unknown",
      ]);
      expect(rows[0].usage).toEqual(getNodeUsage(p, "slow"));
      expect(rows[0].usage.runMs).toBe(40);
      expect(rows[0].usage.totalTokens).toBe(7);
    }
    const usage = getNodeUsage(p, "slow");
    expect(
      tableTime({
        ...usage,
        elapsedMs: 1,
        runMs: 2,
        externalReportedMs: 3,
        externalTaskMs: 4,
      }),
    ).toBe(1);
    expect(
      tableTime({
        ...usage,
        elapsedMs: null,
        runMs: null,
        externalReportedMs: 3,
        externalTaskMs: 4,
      }),
    ).toBe(3);
  });

  it("keeps orphaned work and malformed cycle members reachable once, without changing retained relationships", () => {
    const p = project();
    p.nodes = [
      node("orphan", "missing"),
      node("cycle-a", "cycle-b"),
      node("cycle-b", "cycle-a"),
      node("self", "self"),
      node("leaf", "cycle-b"),
    ];
    const before = JSON.stringify(p);
    const rows = view(p, new Set(p.nodes.map((node) => node.id)));
    expect(rows.map((row) => [row.node.id, row.depth])).toEqual([
      ["orphan", 0],
      ["cycle-a", 0],
      ["cycle-b", 1],
      ["leaf", 2],
      ["self", 0],
    ]);
    expect(JSON.stringify(p)).toBe(before);
    const filtered = buildResearchRows(p, {
      expandedIds: new Set(),
      query: "leaf",
    });
    expect(filtered.map((row) => row.node.id)).toEqual([
      "cycle-a",
      "cycle-b",
      "leaf",
    ]);
  });

  it("reads usage lazily and reuses the same measurement for repeated cells", () => {
    const p = project();
    p.nodes = [node("root"), node("child", "root")];
    const spy = vi.spyOn(usageModule, "getNodeUsage");
    try {
      const rows = buildResearchRows(p, { expandedIds: new Set(["root"]) });
      expect(spy).not.toHaveBeenCalled();
      const counters = rows[0].usage;
      expect(spy).toHaveBeenCalledTimes(1);
      expect(rows[0].usage).toBe(counters);
      expect(spy).toHaveBeenCalledTimes(1);
    } finally {
      spy.mockRestore();
    }
  });
  it("traverses deeply nested research iteratively and leaves all project values untouched", () => {
    const p = project();
    p.nodes = Array.from({ length: 1000 }, (_, index) =>
      node(`n${index}`, index ? `n${index - 1}` : null),
    );
    const before = JSON.stringify(p);
    const rows = buildResearchRows(p, {
      expandedIds: new Set(),
      query: "n999",
    });
    expect(rows).toHaveLength(1000);
    expect(rows.at(-1)?.depth).toBe(999);
    expect(rows.at(-1)?.usage.totalTokens).toBeNull();
    expect(JSON.stringify(p)).toBe(before);
  });
});
