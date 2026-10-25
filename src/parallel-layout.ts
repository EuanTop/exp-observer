import type { Edge } from "@xyflow/react";

/** Reserve the middle ports of an explicit shortcut across parallel paths.
 * These are geometry hints, not a classification of research importance. ELK
 * still places the cards and routes the edges, including every original link.
 * Ambiguous, intersecting or cyclic regions keep the normal ELK layout. */
export function parallelPorts(ids: string[], links: Edge[]) {
  const order = new Map(ids.map((id, index) => [id, index]));
  const forward = links.filter(
    (edge) =>
      !edge.data?.layoutReversed &&
      !edge.id.startsWith("layout-") &&
      edge.data?.layoutRelation !== "recorded_after" &&
      (edge.data?.original as { relation?: string })?.relation !==
        "recorded_after",
  );
  const out = new Map<string, Edge[]>(),
    into = new Map<string, Edge[]>();
  for (const edge of forward) {
    out.set(edge.source, [...(out.get(edge.source) ?? []), edge]);
    into.set(edge.target, [...(into.get(edge.target) ?? []), edge]);
  }
  const outgoing = (id: string) => out.get(id) ?? [];
  const incoming = (id: string) => into.get(id) ?? [];
  const ports = new Map<string, number>();
  const axes = new Set<string>();
  for (const axis of forward) {
    const branches = [...new Set(outgoing(axis.source).map((e) => e.target))]
      .filter((id) => id !== axis.target)
      .sort((a, b) => order.get(a)! - order.get(b)!);
    if (
      branches.length < 2 ||
      outgoing(axis.source).length !== branches.length + 1 ||
      incoming(axis.target).length !== branches.length + 1 ||
      outgoing(axis.source).filter((e) => e.target === axis.target).length !== 1
    )
      continue;
    const members = new Set([axis.source, axis.target]);
    const tails: string[] = [];
    let valid = true;
    for (const head of branches) {
      let current = head;
      while (current !== axis.target) {
        if (members.has(current)) {
          valid = false;
          break;
        }
        members.add(current);
        const next = [...new Set(outgoing(current).map((e) => e.target))];
        if (next.length !== 1) {
          valid = false;
          break;
        }
        if (next[0] === axis.target) tails.push(current);
        current = next[0];
      }
      if (!valid) break;
    }
    // External entries or overlapping path constraints must not be forced into
    // a symmetric fork. Feedback remains available to the regular router.
    if (
      !valid ||
      [...members].some(
        (id) =>
          id !== axis.source &&
          incoming(id).some((e) => !members.has(e.source)),
      ) ||
      outgoing(axis.source).some((e) => ports.has(`${e.id}:out`)) ||
      incoming(axis.target).some((e) => ports.has(`${e.id}:in`))
    )
      continue;
    const leftCount = Math.floor(branches.length / 2);
    const ratio = (index: number) =>
      index < leftCount
        ? (0.45 * (index + 1)) / (leftCount + 1)
        : 0.55 +
          (0.45 * (index - leftCount + 1)) / (branches.length - leftCount + 1);
    ports.set(`${axis.id}:out`, 0.5);
    ports.set(`${axis.id}:in`, 0.5);
    branches.forEach((head, index) => {
      // Each visible branch owns its own port; duplicate connections retain
      // ELK's regular free-port routing rather than crowding a fixed slot.
      for (const [suffix, edges] of [
        ["out", outgoing(axis.source).filter((e) => e.target === head)],
        ["in", incoming(axis.target).filter((e) => e.source === tails[index])],
      ] as const)
        edges.forEach((e) => ports.set(`${e.id}:${suffix}`, ratio(index)));
    });
    axes.add(axis.id);
  }
  return { ports, axes };
}
