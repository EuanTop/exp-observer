import type { Project, ResearchNode } from "./model";
import { getNodeUsage, type NodeUsage } from "./usage";

export type ResearchTableSort = "recorded" | "title" | "time" | "tokens";
export type ResearchTableOptions = {
  expandedIds: ReadonlySet<string>;
  query?: string;
  status?: string;
  kind?: string;
  sort?: ResearchTableSort;
  direction?: "asc" | "desc";
};
export type ResearchTableRow = {
  node: ResearchNode;
  depth: number;
  hasChildren: boolean;
  childCount: number;
  expanded: boolean;
  contextOnly: boolean;
  usage: NodeUsage;
};

// Keep the same choice of measurement for display and numeric sorting. These
// clocks remain distinct in the UI; this never adds their different scopes.
export function tableTime(usage: NodeUsage): number | null {
  return (
    usage.elapsedMs ??
    usage.runMs ??
    usage.externalReportedMs ??
    usage.externalTaskMs
  );
}

/** A view of explicit containment, independent of semantic/chronological edges.
 * Expansion, filtering and ordering never mutate the research record. */
export function buildResearchRows(
  project: Project,
  options: ResearchTableOptions = { expandedIds: new Set() },
): ResearchTableRow[] {
  const byId = new Map(project.nodes.map((node) => [node.id, node]));
  const ids = [...byId.keys()];
  const order = new Map(ids.map((id, index) => [id, index]));
  const parents = new Map(
    ids.map((id) => {
      const parent = byId.get(id)!.parentId;
      return [id, parent && parent !== id && byId.has(parent) ? parent : null];
    }),
  );

  // Imported malformed containment must not hang the table or silently lose
  // work. Break only the display cycle, choosing its earliest recorded member.
  const settled = new Set<string>();
  for (const id of ids) {
    const path: string[] = [];
    const seen = new Map<string, number>();
    let current: string | null = id;
    while (current !== null && !settled.has(current)) {
      const repeated = seen.get(current);
      if (repeated !== undefined) {
        const root = path
          .slice(repeated)
          .reduce((a, b) => (order.get(a)! < order.get(b)! ? a : b));
        parents.set(root, null);
        break;
      }
      seen.set(current, path.length);
      path.push(current);
      current = parents.get(current) ?? null;
    }
    for (const member of path) settled.add(member);
  }

  const children = new Map<string | null, string[]>();
  for (const id of ids) {
    const parent = parents.get(id) ?? null;
    const siblings = children.get(parent) ?? [];
    siblings.push(id);
    children.set(parent, siblings);
  }
  const query = options.query?.trim().toLocaleLowerCase() || "";
  const status =
    options.status && options.status !== "all" ? options.status : "";
  const kind = options.kind && options.kind !== "all" ? options.kind : "";
  const filtering = !!(query || status || kind);
  const matches = new Set(
    ids.filter((id) => {
      const node = byId.get(id)!;
      return (
        (!status || node.status === status) &&
        (!kind || node.kind === kind) &&
        (!query ||
          [
            node.title,
            node.summary,
            node.conclusion,
            node.notes,
            node.nextAction,
            node.pauseReason,
            node.resumeWhen,
            node.id,
            ...(node.tags || []),
          ]
            .filter((value): value is string => typeof value === "string")
            .join("\n")
            .toLocaleLowerCase()
            .includes(query))
      );
    }),
  );
  const included = new Set(matches);
  if (filtering)
    for (const id of matches) {
      let parent = parents.get(id) ?? null;
      while (parent !== null && !included.has(parent)) {
        included.add(parent);
        parent = parents.get(parent) ?? null;
      }
    }

  const usage = new Map<string, NodeUsage>();
  const usageFor = (id: string) => {
    if (!usage.has(id)) usage.set(id, getNodeUsage(project, id));
    return usage.get(id)!;
  };
  const sort = options.sort ?? "recorded";
  const direction = options.direction === "desc" ? -1 : 1;
  const collator = new Intl.Collator(undefined, {
    numeric: true,
    sensitivity: "base",
  });
  const compare = (a: string, b: string) => {
    const stable = order.get(a)! - order.get(b)!;
    if (sort === "recorded") return stable * direction;
    if (sort === "title")
      return (
        collator.compare(byId.get(a)!.title, byId.get(b)!.title) * direction ||
        stable
      );
    const valueA =
      sort === "time" ? tableTime(usageFor(a)) : usageFor(a).totalTokens;
    const valueB =
      sort === "time" ? tableTime(usageFor(b)) : usageFor(b).totalTokens;
    if (valueA === null) return valueB === null ? stable : 1;
    if (valueB === null) return -1;
    return (valueA - valueB) * direction || stable;
  };
  const sortedChildren = (parent: string | null) =>
    (children.get(parent) ?? [])
      .filter((id) => !filtering || included.has(id))
      .slice()
      .sort(compare);
  const stack = sortedChildren(null)
    .reverse()
    .map((id) => ({ id, depth: 0 }));
  const result: ResearchTableRow[] = [];
  while (stack.length) {
    const { id, depth } = stack.pop()!;
    const members = children.get(id) ?? [];
    const visibleMembers = sortedChildren(id);
    const expanded =
      members.length > 0 &&
      (filtering ? visibleMembers.length > 0 : options.expandedIds.has(id));
    result.push({
      node: byId.get(id)!,
      depth,
      hasChildren: members.length > 0,
      childCount: members.length,
      expanded,
      contextOnly: filtering && !matches.has(id),
      // Structural filtering/expansion must not calculate every subtree's
      // counters. Read them only when a displayed cell or metric sort needs it.
      get usage() {
        return usageFor(id);
      },
    });
    if (expanded)
      for (const child of visibleMembers.reverse())
        stack.push({ id: child, depth: depth + 1 });
  }
  return result;
}
