import type { Project, ResearchNode } from "./model";

const text = (value: unknown): string =>
  typeof value === "string" ? value.trim() : "";

export type NodePresentation = {
  headline: string;
  context: string;
  summary: string;
  source: string;
  conclusion?: string;
  pauseReason?: string;
  resumeWhen?: string;
  nextAction?: string;
};

// Preserve the research question/work as the title. Show recorded findings in
// the body, without turning arbitrary metrics into a generated narrative.
export function nodePresentation(
  project: Project,
  node: ResearchNode,
): NodePresentation {
  const decision = [...(project.decisions ?? [])]
    .reverse()
    .find(
      (decision) => decision.nodeId === node.id && text(decision.conclusion),
    );
  const runIds = new Set(
    (project.runs ?? [])
      .filter((run) => run.nodeId === node.id)
      .map((run) => run.id),
  );
  const replaced = new Set(
    (project.assessments ?? []).map((assessment) => assessment.supersedes),
  );
  const assessment = [...(project.assessments ?? [])]
    .reverse()
    .find(
      (assessment) =>
        runIds.has(assessment.runId) &&
        !replaced.has(assessment.id) &&
        text(assessment.conclusion),
    );
  const latestFinding = [...(project.nodes ?? [])]
    .reverse()
    .find(
      (child) =>
        child.parentId === node.id &&
        ["finding", "correction", "decision"].includes(child.kind) &&
        child.status === "completed" &&
        (text(child.conclusion) || text(child.title)),
    );
  const conclusion =
    text(node.conclusion) ||
    text(decision?.conclusion) ||
    text(assessment?.conclusion) ||
    text(latestFinding?.conclusion) ||
    text(latestFinding?.title);
  // Show recorded prose, never manufacture a result from metrics or status.
  const paragraphs = text(node.notes).split(/\n\s*\n/);
  const notesPreview = (
    paragraphs.find((p) =>
      /^(?:对研究问题的回答|研究结论|Conclusion)[:：]/i.test(p),
    ) ||
    paragraphs[0] ||
    ""
  ).slice(0, 700);
  const hasDistinctConclusion = !!conclusion && conclusion !== text(node.title);
  const summary =
    text(node.summary) ||
    (!hasDistinctConclusion ? notesPreview : "") ||
    (!hasDistinctConclusion ? text(node.nextAction) : "");
  const source = text(node.conclusion)
    ? "结论"
    : text(decision?.conclusion)
      ? "决策"
      : text(assessment?.conclusion)
        ? `评估 · ${assessment!.rubric}`
        : latestFinding
          ? "最近发现"
          : "";
  const distinctConclusion =
    conclusion !== summary && conclusion !== text(node.title) ? conclusion : "";
  const pauseReason = node.status === "paused" ? text(node.pauseReason) : "";
  const resumeWhen = node.status === "paused" ? text(node.resumeWhen) : "";
  const nextAction =
    node.status === "paused" && !resumeWhen ? text(node.nextAction) : "";
  return {
    headline: text(node.title) || "未命名节点",
    context: "",
    summary:
      summary && [pauseReason, resumeWhen, nextAction].includes(summary)
        ? ""
        : summary,
    conclusion: distinctConclusion,
    source: distinctConclusion ? source : "",
    ...(pauseReason ? { pauseReason } : {}),
    ...(resumeWhen ? { resumeWhen } : {}),
    ...(nextAction ? { nextAction } : {}),
  };
}

export function isNodeProcessing(
  project: Project,
  node: ResearchNode,
): boolean {
  // A live executor snapshot takes precedence over historical run records.
  // An open research question says nothing about whether somebody is working.
  if (project.runtimeActivity !== undefined)
    return project.runtimeActivity.some(
      (activity) => activity.nodeId === node.id,
    );
  return (
    (project.runs ?? []).some(
      (run) =>
        run.nodeId === node.id && run.status === "running" && !run.finishedAt,
    ) ||
    (project.observations ?? []).some(
      (observation) =>
        observation.nodeId === node.id &&
        observation.status === "running" &&
        !observation.finishedAt,
    )
  );
}
