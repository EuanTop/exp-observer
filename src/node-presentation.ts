import type { Project, ResearchNode } from "./model";

const text = (value: unknown): string =>
  typeof value === "string" ? value.trim() : "";

export type NodePresentation = {
  headline: string;
  context: string;
  summary: string;
  source: string;
};

// Display recorded statements verbatim. Metrics remain separately labelled facts.
export function nodePresentation(
  project: Project,
  node: ResearchNode,
): NodePresentation {
  const decision = [...project.decisions]
    .reverse()
    .find(
      (decision) => decision.nodeId === node.id && text(decision.conclusion),
    );
  const runIds = new Set(
    project.runs.filter((run) => run.nodeId === node.id).map((run) => run.id),
  );
  const replaced = new Set(
    project.assessments.map((assessment) => assessment.supersedes),
  );
  const assessment = [...project.assessments]
    .reverse()
    .find(
      (assessment) =>
        runIds.has(assessment.runId) &&
        !replaced.has(assessment.id) &&
        text(assessment.conclusion),
    );
  const conclusion =
    text(node.conclusion) ||
    text(decision?.conclusion) ||
    text(assessment?.conclusion);
  const summary = text(node.summary);
  const headline = conclusion || summary || node.title;
  const source = text(node.conclusion)
    ? "结论"
    : text(decision?.conclusion)
      ? "决策"
      : text(assessment?.conclusion)
        ? `评估 · ${assessment!.rubric}`
        : "";
  return {
    headline,
    context: headline !== node.title ? node.title : "",
    summary: conclusion && summary !== conclusion ? summary : "",
    source,
  };
}
