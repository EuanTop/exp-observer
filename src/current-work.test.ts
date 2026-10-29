import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type FocusSession, type FocusSnapshot } from "./api";
import {
  activeWorkNodeIds,
  currentWork,
  initialResearchScope,
  nodeNavigation,
} from "./current-work";
import { WorkChoices } from "./components/CurrentWork";
import { setLocale } from "./i18n";
import type { Project, ResearchNode } from "./model";
const node = (id: string, parentId: string | null = null): ResearchNode => ({
  id,
  parentId,
  title: id,
  kind: "question",
  status: "active",
  summary: "",
  notes: "",
  nextAction: "",
  tags: [],
  collapsed: false,
  position: { x: 0, y: 0 },
});
const project = (): Project => ({
  id: "study",
  name: "Study",
  description: "",
  revision: 1,
  createdAt: "",
  updatedAt: "",
  nodes: [
    node("root"),
    node("branch-a", "root"),
    node("branch-b", "root"),
    node("nested", "branch-a"),
  ],
  edges: [],
  runs: [],
  artifacts: [],
  assessments: [],
  decisions: [],
  activity: [],
});
const now = Date.parse("2026-10-29T10:00:00Z");
const session = (extra: Partial<FocusSession> = {}): FocusSession => ({
  leaseId: "lease-a",
  ownerId: "owner-a",
  label: "Analysis",
  nodeIds: ["nested"],
  startedAt: "2026-10-29T09:55:00Z",
  lastSeenAt: "2026-10-29T09:59:00Z",
  expiresAt: "2026-10-29T10:10:00Z",
  state: "active",
  revision: 1,
  ...extra,
});
const snapshot = (sessions: FocusSession[]): FocusSnapshot => ({
  projectId: "study",
  checkedAt: "2026-10-29T10:00:00Z",
  sessions,
});
afterEach(() => {
  vi.unstubAllGlobals();
  setLocale("en");
});

describe("current work navigation", () => {
  it("keeps simultaneous conversations and multiple nodes independent while deduplicating the jump count", () => {
    const groups = currentWork(
      project(),
      snapshot([
        session({ nodeIds: ["nested", "branch-a", "nested"] }),
        session({
          leaseId: "lease-b",
          ownerId: "owner-b",
          label: "Review",
          nodeIds: ["nested", "branch-b"],
        }),
      ]),
      null,
      now,
    );
    expect(groups).toHaveLength(2);
    expect(groups[0].nodeIds).toEqual(["nested", "branch-a"]);
    expect(activeWorkNodeIds(groups)).toEqual([
      "nested",
      "branch-a",
      "branch-b",
    ]);
    expect(groups.map((group) => group.ownerId)).toEqual([
      "owner-a",
      "owner-b",
    ]);
  });
  it("never treats open questions, expired or ended conversations as executing", () => {
    expect(currentWork(project(), null, null, now)).toEqual([]);
    const groups = currentWork(
      project(),
      snapshot([
        session({ expiresAt: "2026-10-29T09:59:59Z" }),
        session({ leaseId: "closed", state: "ended" }),
        session({ leaseId: "bad", expiresAt: "invalid" }),
      ]),
      null,
      now,
    );
    expect(groups.map((group) => group.state)).toEqual(["stale", "stale"]);
    expect(activeWorkNodeIds(groups)).toEqual([]);
    expect(project().nodes.every((node) => node.status === "active")).toBe(
      true,
    );
  });
  it("isolates project switches and removed node references; captured commands remain a compatible fallback", () => {
    expect(
      currentWork(
        { ...project(), id: "other" },
        snapshot([session()]),
        {
          projectId: "study",
          checkedAt: "",
          active: [{ id: "run", nodeId: "nested", source: "capture" }],
        },
        now,
      ),
    ).toEqual([]);
    const groups = currentWork(
      project(),
      snapshot([session({ nodeIds: ["missing", "nested"] })]),
      {
        projectId: "study",
        checkedAt: "",
        active: [
          { id: "run1", nodeId: "nested", source: "capture" },
          { id: "run2", nodeId: "branch-b", source: "capture" },
          { id: "run3", nodeId: "missing", source: "capture" },
        ],
      },
      now,
    );
    expect(groups[0].nodeIds).toEqual(["nested"]);
    expect(groups[1].nodeIds).toEqual(["branch-b"]);
    expect(groups[1].source).toBe("command");
  });
  it("navigates nested targets to the owning level and opens a historical wrapper without mutation", () => {
    const p = project(),
      before = JSON.stringify(p);
    expect(nodeNavigation(p, "nested")).toEqual({
      projectId: "study",
      nodeId: "nested",
      scope: "branch-a",
    });
    expect(nodeNavigation(p, "root")?.scope).toBe(null);
    expect(nodeNavigation(p, "missing")).toBe(null);
    expect(initialResearchScope(p)).toBe("root");
    expect(initialResearchScope({ ...p, nodes: [node("leaf")] })).toBe(null);
    expect(
      initialResearchScope({
        ...p,
        nodes: [node("root"), node("child", "root")],
      }),
    ).toBe(null);
    expect(
      initialResearchScope({ ...p, nodes: [...p.nodes, node("another-root")] }),
    ).toBe(null);
    expect(JSON.stringify(p)).toBe(before);
  });
  it("renders readable per-conversation choices and distinguishes stale locations in both languages", () => {
    const p = project();
    const groups = currentWork(
      p,
      snapshot([
        session({ label: "Analysis <script>" }),
        session({
          leaseId: "b",
          ownerId: "owner-b",
          label: "",
          nodeIds: ["branch-b"],
          state: "stale",
        }),
      ]),
      null,
      now,
    );
    setLocale("en");
    const html = renderToStaticMarkup(
      createElement(WorkChoices, { project: p, groups, onSelect() {} }),
    );
    expect(html).toContain("Analysis &lt;script&gt;");
    expect(html).toContain("Focused");
    expect(html).toContain("Connection expired");
    expect(html).toContain("Conversation owner-b");
    expect(html).toContain("nested");
    setLocale("zh-CN");
    expect(
      renderToStaticMarkup(
        createElement(WorkChoices, { project: p, groups, onSelect() {} }),
      ),
    ).toContain("已失联");
  });
  it("includes explicitly running remote tasks without pretending the agent is active", () => {
    const p = project();
    p.runs = [
      {
        id: "remote",
        nodeId: "nested",
        title: "GPU training",
        status: "running",
        configuration: { externalTask: true, taskRef: "job-1" },
        metrics: {},
        startedAt: "2026-10-29T09:00:00Z",
        finishedAt: null,
        events: [],
        artifactIds: [],
        origin: "agent",
      },
    ];
    const groups = currentWork(p, null, null, now);
    expect(groups[0]).toMatchObject({
      source: "external",
      nodeIds: ["nested"],
      label: "GPU training",
    });
    const html = renderToStaticMarkup(
      createElement(WorkChoices, { project: p, groups, onSelect() {} }),
    );
    expect(html).toContain("External task · GPU training");
    expect(html).not.toContain("Conversation");
    p.runs[0].status = "completed";
    expect(currentWork(p, null, null, now)).toEqual([]);
  });
  it("passes an abort signal through the encoded project request", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => snapshot([]) });
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    await api.focus("study / ?", controller.signal);
    expect(fetch.mock.calls[0][0]).toBe(
      "/api/projects/study%20%2F%20%3F/focus",
    );
    expect(fetch.mock.calls[0][1].signal).toBe(controller.signal);
  });
});
