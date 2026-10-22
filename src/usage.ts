import {
  isExecutionRun,
  type HostUsageRecord,
  type Observation,
  type Project,
} from "./model";

export type NodeUsage = {
  elapsedMs: number | null;
  elapsedPartial: boolean;
  isRunning: boolean;
  runMs: number | null;
  runCount: number;
  inputTokens: number | null;
  outputTokens: number | null;
  totalTokens: number | null;
  tokensPartial: boolean;
  observations: Observation[];
  hostUsage: HostUsageRecord[];
  cacheReadTokens: number | null;
  cacheWriteTokens: number | null;
};

function nonnegative(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function counter(value: unknown): value is number {
  return nonnegative(value) && Number.isInteger(value);
}

// Records represent stable identities. If an identity occurs twice, its last
// representation wins; it must never contribute twice to an aggregate.
function unique<T extends { id: string }>(records: T[]): T[] {
  return [...new Map(records.map((record) => [record.id, record])).values()];
}

function sumKnown(values: unknown[], valid = nonnegative): number | null {
  const known = values.filter(valid);
  return known.length ? known.reduce((sum, value) => sum + value, 0) : null;
}

export function hostUsageRecords(project: Project): HostUsageRecord[] {
  return [
    ...new Map(
      (project.usageRecords ?? []).map((record) => [
        `${record.source}\u0000${record.sourceRef}`,
        record,
      ]),
    ).values(),
  ];
}

export function getProjectHostUsage(project: Project) {
  const records = hostUsageRecords(project);
  const totals = (entries: HostUsageRecord[]) => ({
    inputTokens: sumKnown(
      entries.map((record) => record.inputTokens),
      counter,
    ),
    outputTokens: sumKnown(
      entries.map((record) => record.outputTokens),
      counter,
    ),
    cacheReadTokens: sumKnown(
      entries.map((record) => record.cacheReadTokens),
      counter,
    ),
    cacheWriteTokens: sumKnown(
      entries.map((record) => record.cacheWriteTokens),
      counter,
    ),
  });
  const groups = new Map<string, HostUsageRecord[]>();
  for (const record of records) {
    const key = `${record.provider}\u0000${record.model}`;
    const group = groups.get(key);
    if (group) group.push(record);
    else groups.set(key, [record]);
  }
  return {
    ...totals(records),
    recordCount: records.length,
    unassignedCount: records.filter((record) => !record.nodeId).length,
    models: [...groups.values()].map((entries) => ({
      provider: entries[0].provider,
      model: entries[0].model,
      ...totals(entries),
      recordCount: entries.length,
    })),
  };
}

function timestamp(value: unknown): number {
  return typeof value === "string" && value.trim() ? Date.parse(value) : NaN;
}

function intervalUnion(observations: Observation[]): number | null {
  const intervals = observations.flatMap((observation): [number, number][] => {
    if (observation.status !== "finished") return [];
    const start = timestamp(observation.startedAt);
    const end = timestamp(observation.finishedAt);
    return Number.isFinite(start) && Number.isFinite(end) && end >= start
      ? [[start, end]]
      : [];
  });
  if (!intervals.length) return null;
  intervals.sort((a, b) => a[0] - b[0]);
  let [start, end] = intervals[0];
  let total = 0;
  for (const [nextStart, nextEnd] of intervals.slice(1)) {
    if (nextStart <= end) end = Math.max(end, nextEnd);
    else {
      total += end - start;
      [start, end] = [nextStart, nextEnd];
    }
  }
  return total + end - start;
}

export function getNodeUsage(project: Project, nodeId: string): NodeUsage {
  const nodes = unique(project.nodes);
  const scope = new Set<string>();
  if (nodes.some((node) => node.id === nodeId)) {
    scope.add(nodeId);
    const queue = [nodeId];
    for (let i = 0; i < queue.length; i++) {
      for (const child of nodes) {
        if (child.parentId === queue[i] && !scope.has(child.id)) {
          scope.add(child.id);
          queue.push(child.id);
        }
      }
    }
  }
  const observations = unique(project.observations ?? [])
    .filter((observation) => scope.has(observation.nodeId))
    .sort((a, b) => {
      const aTime = timestamp(a.startedAt);
      const bTime = timestamp(b.startedAt);
      return (
        (Number.isFinite(bTime) ? bTime : -Infinity) -
          (Number.isFinite(aTime) ? aTime : -Infinity) ||
        a.id.localeCompare(b.id)
      );
    });
  const runs = unique(project.runs).filter(
    (run) => scope.has(run.nodeId) && isExecutionRun(run),
  );
  const hostUsage = hostUsageRecords(project).filter(
    (record) => record.nodeId !== null && scope.has(record.nodeId),
  );
  const tokenObservations = observations.filter(
    (observation) =>
      !hostUsage.some(
        (record) =>
          record.source === observation.usageSource &&
          record.sourceRef === observation.usageRef,
      ),
  );
  const inputTokens = sumKnown(
    [
      ...tokenObservations.map((o) => o.inputTokens),
      ...hostUsage.map((record) => record.inputTokens),
    ],
    counter,
  );
  const outputTokens = sumKnown(
    [
      ...tokenObservations.map((o) => o.outputTokens),
      ...hostUsage.map((record) => record.outputTokens),
    ],
    counter,
  );
  const totalTokens = sumKnown([inputTokens, outputTokens], counter);
  const observedNodes = new Set([
    ...observations.map((o) => o.nodeId),
    ...hostUsage.map((record) => record.nodeId),
  ]);
  const parents = new Set(nodes.map((node) => node.parentId));
  const unobservedWorkedLeaf = nodes.some(
    (node) =>
      scope.has(node.id) &&
      node.status !== "proposed" &&
      !parents.has(node.id) &&
      !["group", "container"].includes(node.kind) &&
      !observedNodes.has(node.id),
  );
  const isRunning = observations.some((o) => o.status === "running");
  return {
    elapsedMs: intervalUnion(observations),
    elapsedPartial: isRunning,
    isRunning,
    runMs: sumKnown(runs.map((run) => run.metrics?.wallTimeMs)),
    runCount: runs.length,
    inputTokens,
    outputTokens,
    totalTokens,
    tokensPartial:
      tokenObservations.some(
        (o) => !counter(o.inputTokens) || !counter(o.outputTokens),
      ) ||
      hostUsage.some(
        (record) =>
          !counter(record.inputTokens) || !counter(record.outputTokens),
      ) ||
      (totalTokens !== null && unobservedWorkedLeaf),
    observations,
    hostUsage,
    cacheReadTokens: sumKnown(
      hostUsage.map((record) => record.cacheReadTokens),
      counter,
    ),
    cacheWriteTokens: sumKnown(
      hostUsage.map((record) => record.cacheWriteTokens),
      counter,
    ),
  };
}

const compactNumber = (value: number) =>
  value.toLocaleString("en-US", {
    maximumFractionDigits: 1,
    useGrouping: false,
  });

export function formatDuration(ms: number | null | undefined): string {
  if (!nonnegative(ms)) return "—";
  if (ms < 1000) return `${compactNumber(ms)} ms`;
  if (ms < 60_000) return `${compactNumber(ms / 1000)} s`;
  if (ms < 3_600_000) return `${compactNumber(ms / 60_000)} m`;
  return `${compactNumber(ms / 3_600_000)} h`;
}

export function formatTokens(n: number | null | undefined): string {
  if (!counter(n)) return "—";
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${compactNumber(n / 1000)}k`;
  if (n < 1_000_000_000) return `${compactNumber(n / 1_000_000)}M`;
  return `${compactNumber(n / 1_000_000_000)}B`;
}
