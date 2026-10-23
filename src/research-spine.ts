import { ancestry, isVisualContainer, type Project } from "./model";

/** A view projection only. Recorded nodes/relations are never changed. */
export function researchSpine(project: Project): Project {
  const known = new Set(project.nodes.map((n) => n.id));
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
  // Capture chronology is useful in the complete view, but is not a link in
  // the research spine, even when both chronological endpoints are retained.
  const semantic = project.edges.filter(
    (e) =>
      e.relation !== "recorded_after" &&
      known.has(e.source) &&
      known.has(e.target),
  );
  const edges = semantic.filter(
    (e) => kept.has(e.source) && kept.has(e.target),
  );
  const outgoing = new Map<string, typeof project.edges>();
  for (const edge of semantic)
    outgoing.set(edge.source, [...(outgoing.get(edge.source) || []), edge]);

  for (const source of kept) {
    const queue = [source];
    const shortest = new Map<string, string[]>([[source, []]]);
    const traversed: typeof project.edges = [];
    // Stop at the next visible node. Retain the traversed subgraph instead of
    // enumerating every path: merging branches and feedback can be exponential.
    for (let index = 0; index < queue.length; index++) {
      const id = queue[index];
      for (const edge of outgoing.get(id) || []) {
        if (edge.target === source) continue;
        traversed.push(edge);
        if (!shortest.has(edge.target)) {
          shortest.set(edge.target, [...shortest.get(id)!, edge.id]);
          if (!kept.has(edge.target)) queue.push(edge.target);
        }
      }
    }
    const incoming = new Map<string, typeof project.edges>();
    for (const edge of traversed)
      incoming.set(edge.target, [...(incoming.get(edge.target) || []), edge]);
    for (const target of kept) {
      if (target === source || !shortest.has(target)) continue;
      const pending = [target],
        visited = new Set([target]);
      const pathEdges = new Set<string>(),
        hiddenNodes = new Set<string>();
      for (let index = 0; index < pending.length; index++) {
        for (const edge of incoming.get(pending[index]) || []) {
          // A direct edge is already retained with its actual semantics. It
          // must not suppress a separate folded route through hidden work.
          if (edge.source === source && edge.target === target) continue;
          pathEdges.add(edge.id);
          if (edge.source !== source && !visited.has(edge.source)) {
            visited.add(edge.source);
            hiddenNodes.add(edge.source);
            pending.push(edge.source);
          }
        }
      }
      if (!hiddenNodes.size) continue;
      const trace = new Map<string, string[]>([[source, []]]),
        traceQueue = [source];
      for (
        let index = 0;
        index < traceQueue.length && !trace.has(target);
        index++
      ) {
        const id = traceQueue[index];
        for (const edge of outgoing.get(id) || []) {
          if (!pathEdges.has(edge.id) || trace.has(edge.target)) continue;
          trace.set(edge.target, [...trace.get(id)!, edge.id]);
          traceQueue.push(edge.target);
        }
      }
      edges.push({
        id: `spine:${source}:${target}`,
        source,
        target,
        relation: "collapsed_path",
        basis: "unknown",
        label: `经 ${hiddenNodes.size} 个隐藏节点`,
        spinePath: trace.get(target),
        spineEdges: traversed
          .filter((e) => pathEdges.has(e.id))
          .map((e) => e.id),
        spineNodes: project.nodes
          .filter((n) => hiddenNodes.has(n.id))
          .map((n) => n.id),
      });
    }
  }
  return { ...project, nodes, edges };
}
