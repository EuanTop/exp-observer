import type { Project, ResearchNode } from "./model";
import { hostUsageRecords } from "./usage";

export type ProgressionEntry = {
  node: ResearchNode;
  path: string[];
  createdAt: string | null;
};

/** Existing judgments across containers; never a generated research summary. */
export function researchProgression(project: Project): ProgressionEntry[] {
  const nodes = new Map(project.nodes.map((node) => [node.id, node]));
  const entries = project.nodes
    .filter(
      (node) =>
        ["finding", "correction", "decision", "direction"].includes(
          node.kind,
        ) || Boolean(node.conclusion?.trim()),
    )
    .map((node): ProgressionEntry => {
      const path: string[] = [];
      const visited = new Set([node.id]);
      let parent = node.parentId;
      while (parent && !visited.has(parent)) {
        visited.add(parent);
        const ancestor = nodes.get(parent);
        if (!ancestor) break;
        path.unshift(ancestor.title);
        parent = ancestor.parentId;
      }
      const createdAt =
        node.createdAt && Number.isFinite(Date.parse(node.createdAt))
          ? node.createdAt
          : null;
      return { node, path, createdAt };
    });
  // Undated records retain their array positions. Sort only the known-date
  // slots, avoiding fabricated timestamps or a non-transitive mixed comparator.
  const dated = entries
    .filter((entry) => entry.createdAt !== null)
    .sort((a, b) => Date.parse(a.createdAt!) - Date.parse(b.createdAt!));
  let next = 0;
  return entries.map((entry) =>
    entry.createdAt === null ? entry : dated[next++],
  );
}

export function openResearchNodes(project: Project): ResearchNode[] {
  return project.nodes.filter((node) =>
    ["active", "running", "paused"].includes(node.status),
  );
}

export function usageCoverage(project: Project) {
  const records = hostUsageRecords(project);
  const timers = [
    ...new Map(
      (project.observations ?? []).map((timer) => [timer.id, timer]),
    ).values(),
  ];
  const commands = [
    ...new Map(project.runs.map((run) => [run.id, run])).values(),
  ].filter(
    (run) =>
      run.origin === "observed" && Array.isArray(run.configuration?.command),
  );
  const durations = commands
    .map((run) => run.metrics.wallTimeMs)
    .filter(
      (duration): duration is number =>
        typeof duration === "number" &&
        Number.isFinite(duration) &&
        duration >= 0,
    );
  return {
    agentRecords: records.filter((record) => record.scope !== "execution")
      .length,
    executionRecords: records.filter((record) => record.scope === "execution")
      .length,
    unassignedRecords: records.filter((record) => !record.nodeId).length,
    totalRecords: records.length,
    sources: [...new Set(records.map((record) => record.source))],
    stepTimers: timers.length,
    runningTimers: timers.filter((timer) => timer.status === "running").length,
    capturedCommands: commands.length,
    timedCommands: durations.length,
    commandDurationMs: durations.length
      ? durations.reduce((sum, duration) => sum + duration, 0)
      : null,
  };
}
