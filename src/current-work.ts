import type { FocusSnapshot, RuntimeSnapshot } from "./api";
import type { Project } from "./model";

export type WorkGroup = {
  id: string;
  ownerId: string;
  label: string;
  state: "active" | "stale";
  nodeIds: string[];
  source: "conversation" | "command" | "external";
};

// Work leases describe attention, never the scientific status of a question.
export function currentWork(
  project: Project,
  focus: FocusSnapshot | null,
  runtime: RuntimeSnapshot | null,
  now = Date.now(),
): WorkGroup[] {
  const known = new Set(project.nodes.map((node) => node.id));
  const groups: WorkGroup[] = [];
  const covered = new Set<string>();
  if (focus?.projectId === project.id)
    for (const session of focus.sessions) {
      if (session.state === "ended") continue;
      const nodeIds = [...new Set(session.nodeIds)].filter((id) =>
        known.has(id),
      );
      if (!nodeIds.length) continue;
      const expiry = Date.parse(session.expiresAt);
      const state =
        session.state === "active" && Number.isFinite(expiry) && expiry > now
          ? "active"
          : "stale";
      if (state === "active") nodeIds.forEach((id) => covered.add(id));
      groups.push({
        id: `${session.ownerId}:${session.leaseId}`,
        ownerId: session.ownerId,
        label: session.label,
        nodeIds,
        state,
        source: "conversation",
      });
    }
  for (const run of project.runs) {
    if (
      run.configuration?.externalTask !== true ||
      !["queued", "running"].includes(run.status) ||
      !known.has(run.nodeId)
    )
      continue;
    if (!covered.has(run.nodeId)) {
      groups.push({
        id: `external:${run.id}`,
        ownerId: "",
        label: run.title,
        state: "active",
        nodeIds: [run.nodeId],
        source: "external",
      });
      covered.add(run.nodeId);
    }
  }
  if (runtime?.projectId === project.id) {
    const nodeIds = [
      ...new Set(runtime.active.map((item) => item.nodeId)),
    ].filter((id) => known.has(id) && !covered.has(id));
    if (nodeIds.length)
      groups.push({
        id: "runtime",
        ownerId: "",
        label: "",
        state: "active",
        nodeIds,
        source: "command",
      });
  }
  return groups;
}

export function activeWorkNodeIds(groups: WorkGroup[]): string[] {
  return [
    ...new Set(
      groups
        .filter((group) => group.state === "active")
        .flatMap((group) => group.nodeIds),
    ),
  ];
}

// Historical projects can wrap their entire study in one container. Opening its
// first level makes the existing structure readable without rewriting records.
export function initialResearchScope(project: Project): string | null {
  const roots = project.nodes.filter((node) => !node.parentId);
  if (roots.length !== 1) return null;
  const root = roots[0];
  return project.nodes.filter((node) => node.parentId === root.id).length >= 2
    ? root.id
    : null;
}

export function nodeNavigation(project: Project, id: string) {
  const node = project.nodes.find((candidate) => candidate.id === id);
  return node
    ? { projectId: project.id, nodeId: node.id, scope: node.parentId || null }
    : null;
}
