import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { setLocale } from "./i18n";
import type { HostUsageRecord, Project, ResearchNode, Run } from "./model";
import {
  openResearchNodes,
  researchProgression,
  usageCoverage,
} from "./research-progression";
import { ProjectInspector } from "./components/Inspectors";
import { ProjectHostUsage } from "./components/HostUsage";
import { NodeUsagePanel } from "./components/NodeUsagePanel";

const node = (id: string, patch: Partial<ResearchNode> = {}): ResearchNode => ({
  id,
  title: id,
  kind: "question",
  status: "completed",
  parentId: null,
  summary: "",
  notes: "",
  nextAction: "",
  tags: [],
  position: { x: 0, y: 0 },
  collapsed: true,
  ...patch,
});
const project = (nodes: ResearchNode[] = []): Project => ({
  id: "study",
  name: "Retained study",
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
const record = (
  id: string,
  patch: Partial<HostUsageRecord> = {},
): HostUsageRecord => ({
  id,
  nodeId: "finding",
  source: "codex-session",
  sourceRef: id,
  provider: "retained",
  model: "measured",
  inputTokens: 10,
  outputTokens: 2,
  cacheReadTokens: 8,
  cacheWriteTokens: null,
  startedAt: null,
  finishedAt: null,
  ...patch,
});
const command = (id: string, patch: Partial<Run> = {}): Run => ({
  id,
  nodeId: "finding",
  title: id,
  status: "completed",
  configuration: { command: ["python", "study.py"] },
  metrics: { wallTimeMs: 10 },
  startedAt: null,
  artifactIds: [],
  events: [],
  origin: "observed",
  ...patch,
});

describe("recorded research progression", () => {
  it("exposes nested real findings and corrections without flattening or changing research records", () => {
    const p = project([
      node("root", { isContainer: true, title: "Central question" }),
      node("branch", {
        parentId: "root",
        isContainer: true,
        title: "Failure analysis",
      }),
      node("earlier", {
        parentId: "branch",
        kind: "finding",
        title: "The initial result",
        createdAt: "2026-10-26T01:00:00Z",
      }),
      node("later", {
        parentId: "branch",
        kind: "correction",
        conclusion: "The earlier estimate omitted a retained cost",
        createdAt: "2026-10-26T02:00:00Z",
      }),
      node("custom", {
        kind: "boundary-review",
        conclusion: "The causal explanation remains unknown",
        parentId: "root",
      }),
      node("plain-experiment", { kind: "experiment" }),
    ]);
    const before = JSON.stringify(p);
    const entries = researchProgression(p);
    expect(entries.map((entry) => entry.node.id)).toEqual([
      "earlier",
      "later",
      "custom",
    ]);
    expect(entries[1].path).toEqual(["Central question", "Failure analysis"]);
    expect(entries[1].node.conclusion).toBe(
      "The earlier estimate omitted a retained cost",
    );
    expect(JSON.stringify(p)).toBe(before);
  });

  it("orders dated judgments chronologically while undated and invalid dates retain recorded positions", () => {
    const p = project([
      node("late", { kind: "finding", createdAt: "2026-10-26T03:00:00Z" }),
      node("undated", { kind: "finding" }),
      node("early", { kind: "correction", createdAt: "2026-10-26T01:00:00Z" }),
      node("invalid", { kind: "finding", createdAt: "not a date" }),
      node("middle", { kind: "finding", createdAt: "2026-10-26T02:00:00Z" }),
    ]);
    expect(researchProgression(p).map((entry) => entry.node.id)).toEqual([
      "early",
      "undated",
      "middle",
      "invalid",
      "late",
    ]);
    expect(researchProgression(p)[3].createdAt).toBeNull();
  });

  it("includes paused questions and tolerates missing or cyclic parent metadata", () => {
    const p = project([
      node("paused", {
        status: "paused",
        pauseReason: "Needs independent data",
        parentId: "missing",
      }),
      node("active", { status: "active" }),
      node("running", { status: "running" }),
      node("cycle-a", { kind: "finding", parentId: "cycle-b" }),
      node("cycle-b", { parentId: "cycle-a" }),
    ]);
    expect(openResearchNodes(p).map((entry) => entry.id)).toEqual([
      "paused",
      "active",
      "running",
    ]);
    expect(researchProgression(p)[0].path).toEqual(["cycle-b"]);
  });

  it("renders the latest five retained judgments and a real expansion control even when all are nested", () => {
    setLocale("en");
    const p = project([
      node("root", { isContainer: true }),
      ...Array.from({ length: 8 }, (_, index) =>
        node(`judgment-${index}`, {
          title: `Retained judgment ${index}`,
          kind: "finding",
          parentId: "root",
          createdAt: `2026-10-26T0${index}:00:00Z`,
        }),
      ),
      node("paused-question", {
        title: "Unresolved causal explanation",
        parentId: "root",
        status: "paused",
        pauseReason: "Needs independent evidence",
      }),
    ]);
    const html = renderToStaticMarkup(
      createElement(ProjectInspector, {
        project: p,
        onAdd() {},
        onSelect() {},
        onClose() {},
      }),
    );
    expect(html).toContain("Recorded progression");
    expect(html).toContain("Retained judgment 3");
    expect(html).toContain("Retained judgment 7");
    expect(html).not.toContain("Retained judgment 2");
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain("View all 8");
    expect(html).toContain("Unresolved causal explanation");
    expect(html).toContain("Needs independent evidence");
  });
});

describe("measured usage coverage", () => {
  it("counts actual scopes and unassigned records independently without counting duplicate source receipts", () => {
    const p = project();
    p.usageRecords = [
      record("agent"),
      record("same-receipt", { sourceRef: "agent", inputTokens: 99 }),
      record("execution", { scope: "execution", nodeId: null }),
      record("unassigned", { nodeId: null }),
    ];
    expect(usageCoverage(p)).toMatchObject({
      agentRecords: 2,
      executionRecords: 1,
      unassignedRecords: 2,
      totalRecords: 3,
    });
  });

  it("separates step timers from commands and excludes external metrics, mocks and invalid durations", () => {
    const p = project();
    p.runs = [
      command("measured"),
      command("measured", { metrics: { wallTimeMs: 20 } }),
      command("zero", { metrics: { wallTimeMs: 0 } }),
      command("negative", { metrics: { wallTimeMs: -2 } }),
      command("external", {
        configuration: { capturedExternalResult: true },
        metrics: { wallTimeMs: 50000 },
      }),
      command("mock", { origin: "mock" }),
      command("unknown", { metrics: {} }),
    ];
    p.observations = [
      {
        id: "timer",
        nodeId: "finding",
        title: "A recorded work interval",
        status: "running",
        startedAt: "2026-10-26T00:00:00Z",
        finishedAt: null,
        durationMs: null,
        inputTokens: null,
        outputTokens: null,
        usageSource: "",
        origin: "observed",
      },
    ];
    expect(usageCoverage(p)).toMatchObject({
      stepTimers: 1,
      runningTimers: 1,
      capturedCommands: 4,
      timedCommands: 2,
      commandDurationMs: 20,
    });
    expect(usageCoverage(project()).commandDurationMs).toBeNull();
  });

  it("shows uncollected scopes explicitly instead of a zero cost or a complete-research claim", () => {
    setLocale("en");
    const p = project();
    p.usageRecords = [record("measured", { inputTokens: 0, outputTokens: 0 })];
    const html = renderToStaticMarkup(
      createElement(ProjectHostUsage, { project: p }),
    );
    expect(html).toMatch(/Evaluated execution<\/dt><dd>Not collected/);
    expect(html).toMatch(/Step timers<\/dt><dd>Not collected/);
    expect(html).toMatch(/Command time sum<\/dt><dd>Not collected/);
    expect(html).toContain("codex-session");
    expect(html).toMatch(/Input tokens<\/dt><dd>0/);
    const unknown = node("unknown");
    const nodeHtml = renderToStaticMarkup(
      createElement(NodeUsagePanel, {
        project: project([unknown]),
        node: unknown,
        busy: false,
        mutate: async () => true,
      }),
    );
    expect(nodeHtml).toContain("No attributable usage collected");
    expect(nodeHtml).not.toContain("Research agent usage");
  });

  it("uses the Chinese interface for the same retained facts", () => {
    setLocale("zh-CN");
    const html = renderToStaticMarkup(
      createElement(ProjectHostUsage, { project: project() }),
    );
    expect(html).toContain("用量覆盖");
    expect(html).toContain("未采集");
    expect(html).not.toContain("Not collected");
  });
});
