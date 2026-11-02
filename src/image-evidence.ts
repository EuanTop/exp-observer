import type { Artifact, Project } from "./model";

export const IMAGE_PREVIEW_LIMIT = 20 * 1024 * 1024;
export const NODE_FIGURE_HEIGHT = 190;
const imageTypes = new Set([
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
  "image/avif",
  "image/bmp",
  "image/x-ms-bmp",
  "image/x-icon",
  "image/vnd.microsoft.icon",
  "image/svg+xml",
]);
export function isImageEvidence(artifact: Artifact): boolean {
  const mime = (artifact.mime || "").split(";", 1)[0].trim().toLowerCase();
  return imageTypes.has(mime === "image/jpg" ? "image/jpeg" : mime);
}
export const isSvgEvidence = (artifact: Artifact) =>
  (artifact.mime || "").split(";", 1)[0].trim().toLowerCase() ===
  "image/svg+xml";
export const artifactEndpoint = (projectId: string, artifactId: string) =>
  `/api/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}`;
export const evidenceImageUrl = (projectId: string, artifact: Artifact) =>
  `${artifactEndpoint(projectId, artifact.id)}/image`;

// Only explicit ownership and retained artifact references establish membership.
// A support/related edge never transfers an image to a different research step.
export function nodeEvidence(project: Project, nodeId: string): Artifact[] {
  const runs = project.runs.filter((run) => run.nodeId === nodeId);
  const runIds = new Set(runs.map((run) => run.id));
  const linkedIds = new Set([
    ...runs.flatMap((run) => run.artifactIds || []),
    ...project.decisions
      .filter((decision) => decision.nodeId === nodeId)
      .flatMap((decision) => decision.artifactIds || []),
    ...project.assessments
      .filter((assessment) => runIds.has(assessment.runId))
      .flatMap((assessment) => assessment.artifactIds || []),
  ]);
  return project.artifacts.filter(
    (artifact) =>
      artifact.nodeId === nodeId ||
      (artifact.runId && runIds.has(artifact.runId)) ||
      linkedIds.has(artifact.id),
  );
}
export type ImageEvidence = {
  artifact: Artifact;
  ownerId: string;
  ownerTitle: string;
  inherited: boolean;
};
export function nodeImages(
  project: Project,
  nodeId: string,
  includeChildren = false,
): ImageEvidence[] {
  const own = nodeEvidence(project, nodeId).filter(isImageEvidence);
  const ids = new Set([nodeId]);
  if (includeChildren && !own.length) {
    const pending = [nodeId];
    while (pending.length) {
      const parent = pending.pop();
      for (const node of project.nodes)
        if (node.parentId === parent && !ids.has(node.id)) {
          ids.add(node.id);
          pending.push(node.id);
        }
    }
  }
  const owners = new Map<string, string>();
  for (const id of ids)
    for (const artifact of nodeEvidence(project, id))
      if (isImageEvidence(artifact) && !owners.has(artifact.id))
        owners.set(artifact.id, id);
  const seen = new Set<string>();
  return [...project.artifacts].reverse().flatMap((artifact) => {
    const ownerId = owners.get(artifact.id);
    const key = artifact.sha256 || artifact.id;
    if (!ownerId || seen.has(key)) return [];
    seen.add(key);
    return [
      {
        artifact,
        ownerId,
        ownerTitle:
          project.nodes.find((node) => node.id === ownerId)?.title || ownerId,
        inherited: ownerId !== nodeId,
      },
    ];
  });
}
