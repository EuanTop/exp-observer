import type { Observation, Project } from "./model";

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
  const runs = unique(project.runs).filter((run) => scope.has(run.nodeId));
  const inputTokens = sumKnown(
    observations.map((o) => o.inputTokens),
    counter,
  );
  const outputTokens = sumKnown(
    observations.map((o) => o.outputTokens),
    counter,
  );
  const totalTokens = sumKnown([inputTokens, outputTokens], counter);
  const observedNodes = new Set(observations.map((o) => o.nodeId));
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
      observations.some(
        (o) => !counter(o.inputTokens) || !counter(o.outputTokens),
      ) ||
      (totalTokens !== null && unobservedWorkedLeaf),
    observations,
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
