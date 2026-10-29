import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it } from "vitest";
import { NodeInspector } from "./components/Inspectors";
import { setLocale } from "./i18n";
import type { Project, ResearchNode } from "./model";

afterEach(() => setLocale("en"));
it("preserves an existing running or custom status in the inspector selector", () => {
  setLocale("en");
  const node: ResearchNode = {
    id: "record",
    title: "Existing research",
    kind: "question",
    status: "running",
    parentId: null,
    summary: "",
    notes: "",
    nextAction: "",
    tags: [],
    position: { x: 0, y: 0 },
    collapsed: false,
  };
  const project: Project = {
    id: "study",
    name: "Study",
    description: "",
    revision: 1,
    createdAt: "",
    updatedAt: "",
    nodes: [node],
    runs: [],
    edges: [],
    artifacts: [],
    assessments: [],
    decisions: [],
    activity: [],
  };
  const render = () =>
    renderToStaticMarkup(
      createElement(NodeInspector, {
        node,
        project,
        busy: false,
        tab: "overview",
        onTabChange() {},
        mutate: async () => {
          throw new Error("Rendering must not rewrite a recorded status");
        },
        onClose() {},
        onBranch() {},
        onChild() {},
        onEnter() {},
        onDelete() {},
        onArtifact() {},
        onSelect() {},
        onConnect() {},
        onCopyReference() {},
      }),
    );
  expect(render()).toContain(
    '<option value="running" selected="">Running</option>',
  );
  node.status = "awaiting-review";
  expect(render()).toContain(
    '<option value="awaiting-review" selected="">awaiting-review</option>',
  );
  expect(node.status).toBe("awaiting-review");
  node.status = "completed";
  const html = render();
  expect(html).toContain(
    '<option value="completed" selected="">Completed</option>',
  );
  expect(html.match(/<option value="completed"/g)).toHaveLength(1);
});
