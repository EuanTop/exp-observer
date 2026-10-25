import { useLocale } from "../i18n";
import {
  BaseEdge,
  useStore,
  type EdgeProps,
  type ReactFlowState,
} from "@xyflow/react";
import { roundedPath, routeEdge, type Rect } from "../edge-routing";
import type { LayoutRoute } from "../graph-layout";

type CardBounds = Rect & { id: string; parentId?: string; expanded: boolean };
const bounds = (state: ReactFlowState): CardBounds[] =>
  state.nodes
    .filter((n) => !n.hidden)
    .map((node) => {
      const internal = state.nodeLookup.get(node.id)!;
      return {
        id: node.id,
        parentId: node.parentId,
        expanded: !!node.data.expanded,
        ...internal.internals.positionAbsolute,
        width: node.measured?.width ?? Number(node.style?.width ?? 280),
        height:
          node.measured?.height ??
          Number(node.style?.height ?? node.data.layoutHeight ?? 178),
      };
    });
const equalBounds = (a: CardBounds[], b: CardBounds[]) =>
  a.length === b.length &&
  a.every((r, i) => {
    const s = b[i];
    return (
      r.id === s.id &&
      r.x === s.x &&
      r.y === s.y &&
      r.width === s.width &&
      r.height === s.height &&
      r.parentId === s.parentId &&
      r.expanded === s.expanded
    );
  });

export function ResearchEdge(props: EdgeProps) {
  useLocale();
  const cards = useStore(bounds, equalBounds);
  const source = cards.find((n) => n.id === props.source),
    target = cards.find((n) => n.id === props.target);
  if (!source || !target) return null;
  const ancestors = new Set<string>();
  for (const card of [source, target]) {
    let parent = card.parentId;
    while (parent && !ancestors.has(parent)) {
      ancestors.add(parent);
      parent = cards.find((n) => n.id === parent)?.parentId;
    }
  }
  const obstacles = cards
    .filter((n) => n.id !== source.id && n.id !== target.id)
    .map((n) =>
      ancestors.has(n.id) && n.expanded
        ? { ...n, height: Math.min(n.height, 82) }
        : n,
    );
  const label =
    typeof props.label === "string" && props.label.length > 18
      ? props.label.slice(0, 17) + "…"
      : props.label;
  const labelWidth =
    typeof label === "string"
      ? [...label].reduce(
          (sum, character) => sum + (character.charCodeAt(0) > 255 ? 10 : 6),
          16,
        )
      : 90;
  const planned = props.data?.layoutRoute as LayoutRoute | undefined;
  const geometryMatches =
    planned?.geometry.length === cards.length &&
    planned.geometry.every((r) => {
      const card = cards.find((c) => c.id === r.id);
      return (
        card &&
        Math.abs(card.x - r.x) < 0.5 &&
        Math.abs(card.y - r.y) < 0.5 &&
        Math.abs(card.width - r.width) < 0.5 &&
        Math.abs(card.height - r.height) < 0.5
      );
    });
  // ELK plans all ports and channels together. Only a live drag or a manual
  // anchor needs the local obstacle-aware fallback.
  const route = geometryMatches
    ? planned
    : routeEdge(
        source,
        target,
        obstacles,
        Number(props.data?.lane ?? 0),
        labelWidth,
      );
  if (!route) return null;
  const path = roundedPath(route.points);
  return (
    <>
      {typeof props.label === "string" && <title>{props.label}</title>}
      <BaseEdge
        id={props.id}
        path={path}
        markerEnd={props.markerEnd}
        style={props.style}
        label={label}
        labelX={route.label.x}
        labelY={route.label.y}
        labelStyle={props.labelStyle}
        labelBgStyle={props.labelBgStyle}
        labelBgPadding={props.labelBgPadding}
        labelBgBorderRadius={props.labelBgBorderRadius}
      />
      {!props.data?.orderOnly && (
        <path
          d={path}
          className={`research-edge-flow ${props.data?.active ? "is-active" : ""}`}
        />
      )}
    </>
  );
}
