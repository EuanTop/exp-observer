import { beforeEach, describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "./i18n";
import type { Project } from "./model";
import { ResearchTable } from "./components/ResearchTable";
import { subtreeEvidence } from "./image-evidence";

const project = (): Project => ({
  id: "table-study",
  name: "Study",
  description: "",
  revision: 1,
  createdAt: "",
  updatedAt: "",
  activity: [],
  edges: [],
  runs: [],
  assessments: [],
  decisions: [],
  nodes: [
    {
      id: "root",
      title: "Research question",
      kind: "question",
      status: "paused",
      parentId: null,
      summary: "Unknown result",
      notes: "",
      nextAction: "",
      tags: [],
      position: { x: 0, y: 0 },
      collapsed: true,
    },
    {
      id: "child",
      title: "Retained result",
      kind: "finding",
      status: "completed",
      parentId: "root",
      summary: "Observed, not inferred",
      notes: "",
      nextAction: "",
      tags: [],
      position: { x: 0, y: 300 },
      collapsed: true,
    },
  ],
  artifacts: [
    {
      id: "chart",
      nodeId: "child",
      title: "Learning curve",
      path: "chart.svg",
      mime: "image/svg+xml",
      sha256: "abc",
      bytes: 120,
      origin: "observed",
    },
  ],
});
const render = (p: Project) =>
  renderToStaticMarkup(
    createElement(ResearchTable, {
      project: p,
      onInspect: () => {},
      onGraph: () => {},
      onArtifact: () => {},
    }),
  );
beforeEach(() => setLocale("en"));
describe("research table view", () => {
  it("shows the top-level hierarchy with complete columns and a real image preview without pretending missing usage is zero", () => {
    const html = render(project());
    expect(html).toContain('role="treegrid"');
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('data-row-title="root"');
    expect(html).not.toContain('data-row-title="child"');
    for (const label of [
      "Current conclusion",
      "Time",
      "Token",
      "Evidence",
      "Origin",
      "Not collected",
      "Expand all",
      "All statuses",
    ])
      expect(html).toContain(label);
    expect(html).toContain("/api/projects/table-study/artifacts/chart/image");
    expect(html).toContain("Locate Research question in graph");
    expect(html).not.toContain(">0<");
  });
  it("keeps repeated evidence references unique and never changes the project while rendering", () => {
    const p = project();
    p.decisions = [
      {
        id: "d",
        nodeId: "root",
        title: "",
        scope: "",
        conclusion: "",
        nextAction: "",
        runIds: [],
        artifactIds: ["chart"],
      },
    ];
    const before = JSON.stringify(p);
    expect(subtreeEvidence(p, "root").map((a) => a.id)).toEqual(["chart"]);
    render(p);
    expect(JSON.stringify(p)).toBe(before);
  });
  it("provides Chinese controls and a useful empty state", () => {
    setLocale("zh-CN");
    const p = project();
    p.nodes = [];
    p.artifacts = [];
    const html = render(p);
    expect(html).toContain("表格暂无节点");
    expect(html).toContain("展开全部");
    expect(html).toContain("全部状态");
    expect(html).toContain("0 行 · 0 个节点");
  });
});
