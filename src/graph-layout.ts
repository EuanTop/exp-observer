import type { Edge, Node } from "@xyflow/react";
import type { ElkNode, ElkExtendedEdge } from "elkjs/lib/elk-api";
import type { CanvasData } from "./model";
import type { Point, Rect } from "./edge-routing";
import { straightenRoute } from "./edge-simplification";

export type Canvas = { nodes: Node<CanvasData>[]; edges: Edge[] };
export type LayoutGeometry = Rect & { id: string };
export type LayoutRoute = {
  points: Point[];
  label: Point;
  geometry: LayoutGeometry[];
};
const cache = new Map<string, Promise<Geometry>>();
type Geometry = {
  nodes: Map<string, Rect>;
  routes: Map<string, Omit<LayoutRoute, "geometry">>;
  hidden: Set<string>;
};
let engine: Promise<import("elkjs/lib/elk-api").ELK> | undefined;
const elk = () =>
  (engine ??= import("elkjs/lib/elk.bundled.js").then(
    ({ default: ELK }) => new ELK(),
  ));
const relation = (edge: Edge) =>
  String((edge.data?.original as { relation?: string })?.relation ?? "");
const size = (node: Node) => ({
  width: Number(node.style?.width ?? 368),
  height:
    !node.data?.expanded && node.measured?.height != null
      ? node.measured.height
      : Number(node.style?.height ?? 230),
});
const point = (p: Point): Point => ({
  x: Math.round(p.x * 1000) / 1000,
  y: Math.round(p.y * 1000) / 1000,
});
const labelWidth = (label: string) =>
  [...label].reduce((sum, c) => sum + (c.charCodeAt(0) > 255 ? 10 : 6), 16);
const overlap = (a: Rect, b: Rect, gap = 32) =>
  a.x < b.x + b.width + gap &&
  a.x + a.width + gap > b.x &&
  a.y < b.y + b.height + gap &&
  a.y + a.height + gap > b.y;

/** Layout hints are view geometry, never new scientific relationships. Explicit
 * research parents take precedence over capture chronology. Unattached work
 * follows its recorded predecessor rather than becoming another root in a row. */
export function layoutLinks(
  ids: string[],
  edges: Edge[],
): { links: Edge[]; hidden: Set<string> } {
  const known = new Set(ids);
  const semantic = edges.filter(
    (e) =>
      relation(e) !== "recorded_after" &&
      known.has(e.source) &&
      known.has(e.target),
  );
  const incoming = new Set(semantic.map((e) => e.target));
  const links = [...semantic];
  const hidden = new Set<string>();
  const reaches = (from: string, to: string) => {
    const seen = new Set<string>(),
      pending = [from];
    while (pending.length) {
      const id = pending.pop()!;
      if (id === to) return true;
      if (seen.has(id)) continue;
      seen.add(id);
      for (const e of links) if (e.source === id) pending.push(e.target);
    }
    return false;
  };
  for (const edge of edges.filter((e) => relation(e) === "recorded_after")) {
    if (!known.has(edge.source) || !known.has(edge.target)) continue;
    if (incoming.has(edge.target) || reaches(edge.target, edge.source))
      hidden.add(edge.id);
    else {
      links.push(edge);
      incoming.add(edge.target);
    }
  }
  // Independent questions are stacked by their appearance in the record. These
  // invisible packing constraints do not claim that one caused another.
  ids.forEach((id, index) => {
    if (!index || incoming.has(id)) return;
    const before = ids[index - 1];
    if (!reaches(id, before) && !reaches(before, id)) {
      links.push({ id: `layout-only:${id}`, source: before, target: id });
      incoming.add(id);
    }
  });
  return { links, hidden };
}

async function compute(
  canvas: Canvas,
  resetManual: boolean,
): Promise<Geometry> {
  const engine = await elk();
  const byId = new Map(canvas.nodes.map((n) => [n.id, n]));
  const boxes = new Map<string, Rect>();
  const routes = new Map<string, Omit<LayoutRoute, "geometry">>();
  const hidden = new Set<string>();
  const scopes = new Map<string | undefined, Node<CanvasData>[]>();
  for (const node of canvas.nodes) {
    const parent = byId.has(node.parentId ?? "") ? node.parentId : undefined;
    scopes.set(parent, [...(scopes.get(parent) ?? []), node]);
  }
  const parentOf = (id: string) => byId.get(id)?.parentId;
  const representative = (
    id: string,
    scope: string | undefined,
  ): string | undefined => {
    const seen = new Set<string>();
    while (byId.has(id) && !seen.has(id)) {
      seen.add(id);
      if (parentOf(id) === scope || (!parentOf(id) && !scope)) return id;
      id = parentOf(id)!;
    }
  };
  async function arrange(scope?: string) {
    const members = scopes.get(scope) ?? [];
    if (!members.length) return;
    for (const node of members) await arrange(node.id);
    const projected = canvas.edges.flatMap((edge) => {
      const source = representative(edge.source, scope),
        target = representative(edge.target, scope);
      return source && target && source !== target
        ? [{ ...edge, source, target }]
        : [];
    });
    // An ordinary logical parent is a card, not a container.
    for (const node of members) {
      const parent = node.data.node.parentId;
      if (
        parent &&
        members.some((n) => n.id === parent) &&
        !projected.some((e) => e.source === parent && e.target === node.id)
      )
        projected.push({
          id: `layout-parent:${node.id}`,
          source: parent,
          target: node.id,
        });
    }
    const { links, hidden: hiddenHere } = layoutLinks(
      members.map((n) => n.id),
      projected,
    );
    hiddenHere.forEach((id) => hidden.add(id));
    const ports = new Map<string, NonNullable<ElkNode["ports"]>>(
      members.map((n) => [n.id, []]),
    );
    const connections: ElkExtendedEdge[] = links.map((edge) => {
      const sourcePort = `${edge.id}:out`,
        targetPort = `${edge.id}:in`;
      ports.get(edge.source)!.push({
        id: sourcePort,
        width: 0,
        height: 0,
        layoutOptions: { "elk.port.side": "SOUTH" },
      });
      ports.get(edge.target)!.push({
        id: targetPort,
        width: 0,
        height: 0,
        layoutOptions: { "elk.port.side": "NORTH" },
      });
      const text = typeof edge.label === "string" ? edge.label : "";
      return {
        id: edge.id,
        sources: [sourcePort],
        targets: [targetPort],
        ...(text
          ? { labels: [{ text, width: labelWidth(text), height: 20 }] }
          : {}),
      };
    });
    const graph: ElkNode = await engine.layout({
      id: scope ?? "research",
      layoutOptions: {
        "elk.algorithm": "layered",
        "elk.direction": "DOWN",
        "elk.edgeRouting": "ORTHOGONAL",
        "elk.padding": scope
          ? "[top=100,left=30,bottom=30,right=30]"
          : "[top=40,left=40,bottom=40,right=40]",
        "elk.spacing.nodeNode": "64",
        "elk.layered.spacing.nodeNodeBetweenLayers": "100",
        "elk.layered.spacing.edgeNodeBetweenLayers": "28",
        "elk.layered.spacing.edgeEdgeBetweenLayers": "18",
        "elk.spacing.edgeNode": "24",
        "elk.spacing.edgeEdge": "18",
        "elk.spacing.labelLabel": "14",
        "elk.layered.mergeEdges": "false",
        "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
        "elk.layered.nodePlacement.favorStraightEdges": "true",
        "elk.randomSeed": "1",
      },
      children: members.map((node) => ({
        id: node.id,
        ...size(node),
        ...(boxes.has(node.id)
          ? {
              width: boxes.get(node.id)!.width,
              height: boxes.get(node.id)!.height,
            }
          : {}),
        ports: ports.get(node.id),
        layoutOptions: { "elk.portConstraints": "FIXED_SIDE" },
      })),
      edges: connections,
    });
    for (const child of graph.children ?? [])
      boxes.set(child.id, {
        x: child.x!,
        y: child.y!,
        width: child.width!,
        height: child.height!,
      });
    if (scope) {
      const old = boxes.get(scope) ?? { x: 0, y: 0, ...size(byId.get(scope)!) };
      boxes.set(scope, {
        ...old,
        width: Math.max(368, graph.width!),
        height: Math.max(230, graph.height!),
      });
    }
    for (const edge of graph.edges ?? []) {
      const original = canvas.edges.find((e) => e.id === edge.id);
      // Cross-container routes are completed against the visible card geometry
      // by the drag fallback; never attach a descendant edge to the wrong card.
      if (
        !original ||
        representative(original.source, scope) !== original.source ||
        representative(original.target, scope) !== original.target
      )
        continue;
      const section = edge.sections?.[0];
      if (!section) continue;
      const points = [
        section.startPoint,
        ...(section.bendPoints ?? []),
        section.endPoint,
      ].map(point);
      const label = edge.labels?.[0];
      const middle = points[Math.floor(points.length / 2)];
      routes.set(edge.id, {
        points,
        label:
          label && label.x !== undefined
            ? { x: label.x + label.width! / 2, y: label.y! + label.height! / 2 }
            : middle,
      });
    }
  }
  await arrange();
  const absolute = (id: string): Point => {
    const b = boxes.get(id)!,
      parent = parentOf(id);
    if (!parent || !boxes.has(parent)) return { x: b.x, y: b.y };
    const p = absolute(parent);
    return { x: p.x + b.x, y: p.y + b.y };
  };
  // ELK sections inside a scope are relative to that container.
  for (const [id, route] of routes) {
    const edge = canvas.edges.find((e) => e.id === id)!,
      parent = parentOf(edge.source);
    const offset =
      parent && boxes.has(parent) ? absolute(parent) : { x: 0, y: 0 };
    routes.set(id, {
      points: route.points.map((p) =>
        point({ x: p.x + offset.x, y: p.y + offset.y }),
      ),
      label: { x: route.label.x + offset.x, y: route.label.y + offset.y },
    });
  }
  // Manual coordinates remain user-owned. Their ancestors are anchors too.
  const pinned = new Set<string>();
  if (!resetManual)
    for (const n of canvas.nodes)
      if (n.data.node.positionSource !== "auto") {
        let id: string | undefined = n.id;
        while (id && byId.has(id)) {
          pinned.add(id);
          id = parentOf(id);
        }
      }
  const inputAbsolute = (id: string): Point => {
    const n = byId.get(id)!,
      parent = parentOf(id);
    const p =
      parent && byId.has(parent) ? inputAbsolute(parent) : { x: 0, y: 0 };
    return { x: p.x + n.position.x, y: p.y + n.position.y };
  };
  if (pinned.size) {
    // Resolve only local pin collisions, retaining ELK ordering for everything
    // else. The obstacle-aware edge fallback handles any displaced sections.
    const depth = (id: string | undefined): number =>
      id ? 1 + depth(parentOf(id)) : 0;
    for (const [scope, members] of [...scopes].sort(
      ([a], [b]) => depth(b) - depth(a),
    )) {
      const occupied: Rect[] = [];
      for (const n of [...members].sort(
        (a, b) => Number(pinned.has(b.id)) - Number(pinned.has(a.id)),
      )) {
        const box = boxes.get(n.id)!;
        if (pinned.has(n.id)) ((box.x = n.position.x), (box.y = n.position.y));
        else {
          let hit: Rect | undefined;
          while ((hit = occupied.find((b) => overlap(box, b))))
            box.y = hit.y + hit.height + 64;
        }
        occupied.push(box);
      }
      if (scope && boxes.has(scope)) {
        const b = boxes.get(scope)!;
        b.width = Math.max(
          b.width,
          ...members.map(
            (n) => boxes.get(n.id)!.x + boxes.get(n.id)!.width + 30,
          ),
        );
        b.height = Math.max(
          b.height,
          ...members.map(
            (n) => boxes.get(n.id)!.y + boxes.get(n.id)!.height + 30,
          ),
        );
      }
    }
    if (
      canvas.nodes.some(
        (n) =>
          pinned.has(n.id) &&
          (absolute(n.id).x !== inputAbsolute(n.id).x ||
            absolute(n.id).y !== inputAbsolute(n.id).y),
      )
    )
      throw new Error("Manual layout anchor moved");
    routes.clear();
  }
  if (!pinned.size) {
    const rects = new Map(
      [...boxes].map(([id, b]) => [id, { ...b, ...absolute(id) }]),
    );
    for (const edge of canvas.edges) {
      const route = routes.get(edge.id),
        source = rects.get(edge.source),
        target = rects.get(edge.target);
      if (!route || !source || !target) continue;
      const others = [...routes]
        .filter(([id]) => id !== edge.id)
        .map(([, route]) => route);
      const labels = canvas.edges
        .filter(
          (e) =>
            e.id !== edge.id &&
            typeof e.label === "string" &&
            e.label &&
            routes.has(e.id),
        )
        .map((e) => {
          const at = routes.get(e.id)!.label,
            width = labelWidth(String(e.label));
          return {
            x: at.x - width / 2 - 6,
            y: at.y - 14,
            width: width + 12,
            height: 28,
          };
        });
      routes.set(
        edge.id,
        straightenRoute(
          route,
          source,
          target,
          [...rects]
            .filter(([id]) => id !== edge.source && id !== edge.target)
            .map(([, r]) => r),
          others,
          typeof edge.label === "string" && edge.label
            ? labelWidth(edge.label)
            : 0,
          labels,
        ),
      );
    }
  }
  return { nodes: boxes, routes, hidden };
}

/** One layout engine is shared by initial load, topology updates and relayout.
 * Status, selection and heartbeat changes reuse geometry rather than moving it. */
export async function layoutCanvas(
  canvas: Canvas,
  options: { resetManual?: boolean } = {},
): Promise<Canvas> {
  if (!canvas.nodes.length) return canvas;
  const reset = !!options.resetManual;
  const key = JSON.stringify([
    reset,
    canvas.nodes.map((n) => [
      n.id,
      n.parentId,
      n.data.node.parentId,
      n.data.node.positionSource,
      n.data.expanded,
      n.data.node.positionSource !== "auto" && !reset ? n.position : null,
      n.data.expanded && n.data.node.positionSource === "auto" ? null : size(n),
    ]),
    canvas.edges.map((e) => [e.id, e.source, e.target, relation(e), e.label]),
  ]);
  let pending = cache.get(key);
  if (!pending) {
    pending = compute(canvas, reset);
    cache.set(key, pending);
    if (cache.size > 8) cache.delete(cache.keys().next().value!);
    pending.catch(() => cache.delete(key));
  }
  const geometry = await pending;
  const nodes = canvas.nodes.map((node) => ({
    ...node,
    position: {
      x: geometry.nodes.get(node.id)!.x,
      y: geometry.nodes.get(node.id)!.y,
    },
    data: { ...node.data, layoutHeight: geometry.nodes.get(node.id)!.height },
    style: {
      ...node.style,
      width: geometry.nodes.get(node.id)!.width,
      height: node.data.expanded
        ? geometry.nodes.get(node.id)!.height
        : undefined,
    },
  }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const absolute = (n: Node<CanvasData>): Point => {
    const parent = byId.get(n.parentId ?? "");
    const p = parent ? absolute(parent) : { x: 0, y: 0 };
    return { x: n.position.x + p.x, y: n.position.y + p.y };
  };
  const bounds = nodes.map((n) => ({
    id: n.id,
    ...absolute(n),
    width: geometry.nodes.get(n.id)!.width,
    height: geometry.nodes.get(n.id)!.height,
  }));
  return {
    nodes,
    edges: canvas.edges.map((edge) => ({
      ...edge,
      hidden: geometry.hidden.has(edge.id),
      sourceHandle: "bottom",
      targetHandle: "top",
      data: {
        ...edge.data,
        layoutRoute: geometry.routes.has(edge.id)
          ? { ...geometry.routes.get(edge.id)!, geometry: bounds }
          : undefined,
      },
    })),
  };
}
