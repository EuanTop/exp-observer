import { ancestry, isVisualContainer, type Project } from "./model";

/** A view projection only. Recorded nodes/relations are never changed. */
export function researchSpine(project: Project): Project {
  const kept = new Set(
    project.nodes.filter((n) => n.importance === "critical").map((n) => n.id),
  );
  for (const id of [...kept]) {
    for (const node of ancestry(project.nodes, id)) {
      if (isVisualContainer(node)) kept.add(node.id);
    }
  }
  const nodes = project.nodes
    .filter((n) => kept.has(n.id))
    .map((n) => {
      let parent = project.nodes.find((p) => p.id === n.parentId);
      const seen = new Set<string>();
      while (parent && !kept.has(parent.id) && !seen.has(parent.id)) {
        seen.add(parent.id);
        parent = project.nodes.find((p) => p.id === parent!.parentId);
      }
      return {
        ...n,
        parentId: parent && kept.has(parent.id) ? parent.id : null,
      };
    });
  const edges = project.edges.filter(
    (e) => kept.has(e.source) && kept.has(e.target),
  );
  const pairs = new Set(edges.map((e) => `${e.source}:${e.target}`));
  const outgoing = new Map<string, typeof project.edges>();
  for (const edge of project.edges) {
    // Record chronology must not turn into a scientific relationship.
    if (edge.relation === "recorded_after") continue;
    outgoing.set(edge.source, [...(outgoing.get(edge.source) || []), edge]);
  }
  for (const source of kept) {
    const queue = (outgoing.get(source) || []).map((e) => ({
      id: e.target,
      path: [e.id],
    }));
    const visited = new Set([source]);
    for (let index = 0; index < queue.length; index++) {
      const { id, path } = queue[index];
      if (visited.has(id)) continue;
      visited.add(id);
      if (kept.has(id)) {
        const pair = `${source}:${id}`;
        if (path.length > 1 && !pairs.has(pair)) {
          pairs.add(pair);
          edges.push({
            id: `spine:${source}:${id}`,
            source,
            target: id,
            relation: "collapsed_path",
            basis: "unknown",
            label: `经 ${path.length - 1} 个隐藏节点`,
            spinePath: path,
          } as (typeof edges)[number]);
        }
        continue;
      }
      for (const next of outgoing.get(id) || [])
        queue.push({ id: next.target, path: [...path, next.id] });
    }
  }
  return { ...project, nodes, edges };
}
