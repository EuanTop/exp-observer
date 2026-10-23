import { segmentClear, type Point, type Rect } from "./edge-routing";

type Route = { points: Point[]; label: Point };
const same = (a: number, b: number) => Math.abs(a - b) < 0.01;
const overlaps = (a: Rect, b: Rect) =>
  a.x < b.x + b.width &&
  a.x + a.width > b.x &&
  a.y < b.y + b.height &&
  a.y + a.height > b.y;
const tidy = (points: Point[]) =>
  points.filter((p, i) => {
    if (!i || i === points.length - 1) return true;
    const a = points[i - 1],
      b = points[i + 1];
    return !(
      (same(a.x, p.x) && same(p.x, b.x)) ||
      (same(a.y, p.y) && same(p.y, b.y))
    );
  });
function conflicts(path: Point[], other: Point[]): number {
  let count = 0;
  for (const [i, a] of path.slice(0, -1).entries())
    for (const [j, c] of other.slice(0, -1).entries()) {
      const b = path[i + 1],
        d = other[j + 1];
      const v = same(a.x, b.x),
        w = same(c.x, d.x);
      if (v === w) {
        if (
          v
            ? same(a.x, c.x) &&
              Math.min(Math.max(a.y, b.y), Math.max(c.y, d.y)) -
                Math.max(Math.min(a.y, b.y), Math.min(c.y, d.y)) >
                0.1
            : same(a.y, c.y) &&
              Math.min(Math.max(a.x, b.x), Math.max(c.x, d.x)) -
                Math.max(Math.min(a.x, b.x), Math.min(c.x, d.x)) >
                0.1
        )
          count += 100;
      } else {
        const vertical = v ? [a, b] : [c, d],
          horizontal = v ? [c, d] : [a, b];
        if (
          vertical[0].x > Math.min(horizontal[0].x, horizontal[1].x) + 0.1 &&
          vertical[0].x < Math.max(horizontal[0].x, horizontal[1].x) - 0.1 &&
          horizontal[0].y > Math.min(vertical[0].y, vertical[1].y) + 0.1 &&
          horizontal[0].y < Math.max(vertical[0].y, vertical[1].y) - 0.1
        )
          count++;
      }
    }
  return count;
}

/** ELK remains the global router. Its freely placed top/bottom ports sometimes
 * introduce endpoint doglegs without avoiding an obstacle. Move only those
 * ports within their card, and only if the result adds no crossings, shared
 * trunks, label collisions or node intersections. */
export function straightenRoute(
  route: Route,
  source: Rect,
  target: Rect,
  obstacles: Rect[],
  others: Route[],
  labelWidth = 0,
  otherLabels: Rect[] = [],
): Route {
  if (route.points.length < 3 || source.y + source.height >= target.y)
    return route;
  const original = route.points;
  const first = original[0],
    last = original.at(-1)!;
  if (!same(first.y, source.y + source.height) || !same(last.y, target.y))
    return route;
  const insidePort = (x: number, card: Rect) =>
    x >= card.x + 20 && x <= card.x + card.width - 20;
  const available = (point: Point, end: boolean) =>
    others.every((other) => {
      const port = end ? other.points.at(-1)! : other.points[0];
      return !same(point.y, port.y) || Math.abs(point.x - port.x) >= 14;
    });
  const clear = (path: Point[]) =>
    available(path[0], false) &&
    available(path.at(-1)!, true) &&
    path
      .slice(1)
      .every((p, i) =>
        segmentClear(path[i], p, [
          source,
          target,
          ...obstacles,
          ...otherLabels,
        ]),
      ) &&
    others.every(
      (o) => conflicts(path, o.points) <= conflicts(original, o.points),
    );
  const candidates = [
    last.x,
    first.x,
    (Math.max(source.x, target.x) +
      Math.min(source.x + source.width, target.x + target.width)) /
      2,
  ];
  for (const x of candidates) {
    if (!insidePort(x, source) || !insidePort(x, target)) continue;
    const points = [
      { x, y: first.y },
      { x, y: last.y },
    ];
    const label = { x: x - labelWidth / 2 - 8, y: (first.y + last.y) / 2 };
    const labelBox = {
      x: label.x - labelWidth / 2,
      y: label.y - 12,
      width: labelWidth,
      height: 24,
    };
    if (
      clear(points) &&
      (!labelWidth ||
        ![source, target, ...obstacles, ...otherLabels].some((b) =>
          overlaps(labelBox, b),
        ))
    )
      return { points, label: labelWidth ? label : route.label };
  }
  let points = original;
  if (
    points.length >= 4 &&
    same(points[0].x, points[1].x) &&
    same(points[1].y, points[2].y) &&
    same(points[2].x, points[3].x) &&
    insidePort(points[2].x, source)
  ) {
    const candidate = tidy([
      { x: points[2].x, y: first.y },
      ...points.slice(2),
    ]);
    if (clear(candidate)) points = candidate;
  }
  const n = points.length;
  if (
    n >= 4 &&
    same(points[n - 1].x, points[n - 2].x) &&
    same(points[n - 2].y, points[n - 3].y) &&
    same(points[n - 3].x, points[n - 4].x) &&
    insidePort(points[n - 3].x, target)
  ) {
    const candidate = tidy([
      ...points.slice(0, -2),
      { x: points[n - 3].x, y: last.y },
    ]);
    if (clear(candidate)) points = candidate;
  }
  return { ...route, points };
}
