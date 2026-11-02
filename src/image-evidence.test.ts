import { beforeEach, describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ReactFlowProvider } from "@xyflow/react";
import { setLocale } from "./i18n";
import {
  evidenceImageUrl,
  isImageEvidence,
  nodeEvidence,
  nodeImages,
} from "./image-evidence";
import { toCanvas, type Artifact, type Project } from "./model";
import { ArtifactDialog } from "./components/Dialogs";
import { ResearchCard } from "./components/ResearchCard";
import { EvidenceRow } from "./components/EvidenceMedia";

const node = (id: string, parentId: string | null = null) => ({
  id,
  parentId,
  title: id,
  kind: "finding",
  status: "completed",
  summary: "",
  notes: "",
  nextAction: "",
  tags: [],
  position: { x: 0, y: 0 },
  collapsed: true,
});
const artifact = (id: string, extra: Partial<Artifact> = {}): Artifact => ({
  id,
  title: id + ".svg",
  mime: "image/svg+xml",
  sha256: id,
  bytes: 100,
  path: id + ".svg",
  origin: "observed",
  ...extra,
});
const project = (): Project => ({
  id: "study",
  name: "Study",
  description: "",
  revision: 1,
  createdAt: "",
  updatedAt: "",
  activity: [],
  nodes: [node("root"), node("a", "root"), node("b", "root")],
  edges: [],
  runs: [],
  assessments: [],
  decisions: [],
  artifacts: [],
});
beforeEach(() => setLocale("en"));

describe("image evidence", () => {
  it("recognizes SVG and raster MIME while keeping HTML and misleading names inert", () => {
    for (const mime of [
      "image/svg+xml",
      "image/png",
      "image/jpeg",
      "IMAGE/JPG; charset=utf-8",
      "image/gif",
      "image/webp",
      "image/avif",
      "image/bmp",
      "image/x-icon",
    ])
      expect(isImageEvidence(artifact("a", { mime }))).toBe(true);
    for (const mime of [
      "text/html",
      "text/plain",
      "application/json",
      "application/octet-stream",
    ])
      expect(isImageEvidence(artifact("misleading.png", { mime }))).toBe(false);
    expect(evidenceImageUrl("study/a", artifact("file+b"))).toBe(
      "/api/projects/study%2Fa/artifacts/file%2Bb/image",
    );
  });
  it("finds images on a finding, captured run, assessment or decision without borrowing semantic neighbours", () => {
    const p = project();
    p.runs = [
      {
        id: "run",
        nodeId: "a",
        artifactIds: ["via-run"],
        configuration: {},
        metrics: {},
        status: "completed",
        title: "",
        startedAt: null,
        events: [],
        origin: "observed",
      },
    ];
    p.assessments = [
      {
        id: "review",
        runId: "run",
        metrics: {},
        rubric: "v1",
        conclusion: "",
        limitations: "",
        artifactIds: ["review-image"],
      },
    ];
    p.decisions = [
      {
        id: "decision",
        nodeId: "a",
        title: "Decision",
        scope: "",
        runIds: [],
        conclusion: "",
        nextAction: "",
        artifactIds: ["decision-image"],
      },
    ];
    p.artifacts = [
      artifact("direct", { nodeId: "a" }),
      artifact("via-run"),
      artifact("by-run-id", { runId: "run" }),
      artifact("review-image"),
      artifact("decision-image"),
      artifact("other", { nodeId: "b" }),
    ];
    p.edges = [
      {
        id: "related",
        source: "a",
        target: "b",
        relation: "supports",
        label: "",
        runIds: [],
      },
    ];
    expect(nodeEvidence(p, "a").map((a) => a.id)).toEqual([
      "direct",
      "via-run",
      "by-run-id",
      "review-image",
      "decision-image",
    ]);
    expect(nodeImages(p, "a").some((i) => i.artifact.id === "other")).toBe(
      false,
    );
  });
  it("summarizes a collapsed container using labelled descendant images and deduplicates the same retained image", () => {
    const p = project();
    p.artifacts = [
      artifact("first", { nodeId: "a", sha256: "same" }),
      artifact("copy", { nodeId: "b", sha256: "same" }),
    ];
    expect(nodeImages(p, "root", true)).toEqual([
      {
        artifact: p.artifacts[1],
        ownerId: "b",
        ownerTitle: "b",
        inherited: true,
      },
    ]);
    p.artifacts.push(artifact("own", { nodeId: "root" }));
    expect(nodeImages(p, "root", true).map((i) => i.artifact.id)).toEqual([
      "own",
    ]);
  });
  it("allocates card height for an actual image and binds a direct open action without rewriting project data", () => {
    const p = project();
    const actions = {
      onToggle: () => {},
      onEnter: () => {},
      onArtifact: () => {},
    };
    const plain = toCanvas(p, "root", [], actions).nodes.find(
      (n) => n.id === "a",
    )!;
    p.artifacts = [artifact("chart", { nodeId: "a" })];
    const before = JSON.stringify(p);
    const card = toCanvas(p, "root", [], actions).nodes.find(
      (n) => n.id === "a",
    )!;
    expect(Number(card.style?.height)).toBe(Number(plain.style?.height) + 190);
    expect(card.data.onArtifact).toBe(actions.onArtifact);
    expect(JSON.stringify(p)).toBe(before);
    const html = renderToStaticMarkup(
      createElement(ReactFlowProvider, {
        children: createElement(ResearchCard, {
          ...card,
          data: card.data,
        } as never),
      }),
    );
    expect(html).toContain('src="/api/projects/study/artifacts/chart/image"');
    expect(html).toContain('loading="lazy"');
    expect(html).toContain("View image: chart.svg");
  });
  it("renders SVG as an image document in the evidence dialog and keeps raw source as a separate mode", () => {
    const html = renderToStaticMarkup(
      createElement(ArtifactDialog, {
        artifact: artifact("chart"),
        project: project(),
        onClose: () => {},
      }),
    );
    expect(html).toContain('class="evidence-image"');
    expect(html).toContain('src="/api/projects/study/artifacts/chart/image"');
    expect(html).toContain("Image preview");
    expect(html).toContain("Raw content");
    expect(html).not.toContain("FileReader");
  });
  it("distinguishes picture evidence from data files in lists", () => {
    const svg = renderToStaticMarkup(
      createElement(EvidenceRow, {
        projectId: "study",
        artifact: artifact("chart"),
        onOpen: () => {},
      }),
    );
    const json = renderToStaticMarkup(
      createElement(EvidenceRow, {
        projectId: "study",
        artifact: artifact("values", { mime: "application/json" }),
        onOpen: () => {},
      }),
    );
    expect(svg).toContain('class="artifact-row has-image"');
    expect(svg).toContain("Image · ");
    expect(json).not.toContain("/image");
  });
});
