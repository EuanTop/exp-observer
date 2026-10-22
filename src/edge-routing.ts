export type Point = { x: number; y: number };
export type Rect = Point & { width: number; height: number };
export type Side = "left" | "right" | "top" | "bottom";
export type Route = {
  points: Point[];
  sourceSide: Side;
  targetSide: Side;
  label: Point;
};
const directions: Record<Side, Point> = {
  left: { x: -1, y: 0 },
  right: { x: 1, y: 0 },
  top: { x: 0, y: -1 },
  bottom: { x: 0, y: 1 },
};
const center = (r: Rect) => ({ x: r.x + r.width / 2, y: r.y + r.height / 2 });
const inside = (p: Point, r: Rect) =>
  p.x > r.x + 0.01 &&
  p.x < r.x + r.width - 0.01 &&
  p.y > r.y + 0.01 &&
  p.y < r.y + r.height - 0.01;
const contains = (outer: Rect, inner: Rect) =>
  inner.x >= outer.x &&
  inner.y >= outer.y &&
  inner.x + inner.width <= outer.x + outer.width &&
  inner.y + inner.height <= outer.y + outer.height;
const distance = (a: Point, b: Point) =>
  Math.abs(a.x - b.x) + Math.abs(a.y - b.y);

export function facingSides(source: Rect, target: Rect): [Side, Side] {
  const a = center(source),
    b = center(target);
  const horizontal =
    Math.abs(b.x - a.x) / (source.width + target.width) >=
    Math.abs(b.y - a.y) / (source.height + target.height);
  return horizontal
    ? b.x >= a.x
      ? ["right", "left"]
      : ["left", "right"]
    : b.y >= a.y
      ? ["bottom", "top"]
      : ["top", "bottom"];
}

function port(rect: Rect, side: Side): Point {
  const c = center(rect);
  const horizontal = side === "left" || side === "right";
  return horizontal
    ? { x: side === "left" ? rect.x : rect.x + rect.width, y: c.y }
    : { x: c.x, y: side === "top" ? rect.y : rect.y + rect.height };
}

export function segmentClear(a: Point, b: Point, obstacles: Rect[]): boolean {
  if (a.x !== b.x && a.y !== b.y) return false;
  return obstacles.every((r) =>
    a.x === b.x
      ? !(
          a.x > r.x + 0.01 &&
          a.x < r.x + r.width - 0.01 &&
          Math.max(a.y, b.y) > r.y + 0.01 &&
          Math.min(a.y, b.y) < r.y + r.height - 0.01
        )
      : !(
          a.y > r.y + 0.01 &&
          a.y < r.y + r.height - 0.01 &&
          Math.max(a.x, b.x) > r.x + 0.01 &&
          Math.min(a.x, b.x) < r.x + r.width - 0.01
        ),
  );
}

function simplify(points: Point[]): Point[] {
  const result: Point[] = [];
  for (const p of points) {
    if (result.length && distance(result.at(-1)!, p) < 0.01) continue;
    while (result.length > 1) {
      const a = result.at(-2)!,
        b = result.at(-1)!;
      if ((a.x === b.x && b.x === p.x) || (a.y === b.y && b.y === p.y))
        result.pop();
      else break;
    }
    result.push(p);
  }
  return result;
}

// A small priority queue keeps obstacle routing responsive while cards are dragged.
class Queue {
  items: { id: number; score: number }[] = [];
  push(item: { id: number; score: number }) {
    let index = this.items.length;
    this.items.push(item);
    while (index > 0) {
      const parent = Math.floor((index - 1) / 2);
      if (this.items[parent].score <= item.score) break;
      this.items[index] = this.items[parent];
      index = parent;
    }
    this.items[index] = item;
  }
  pop() {
    const first = this.items[0],
      last = this.items.pop()!;
    if (this.items.length) {
      let index = 0;
      while (index * 2 + 1 < this.items.length) {
        let child = index * 2 + 1;
        if (
          child + 1 < this.items.length &&
          this.items[child + 1].score < this.items[child].score
        )
          child++;
        if (this.items[child].score >= last.score) break;
        this.items[index] = this.items[child];
        index = child;
      }
      this.items[index] = last;
    }
    return first;
  }
}

function corridor(
  start: Point,
  end: Point,
  obstacles: Rect[],
): Point[] | undefined {
  const simple = [
    [start, { x: end.x, y: start.y }, end],
    [start, { x: start.x, y: end.y }, end],
    [
      start,
      { x: (start.x + end.x) / 2, y: start.y },
      { x: (start.x + end.x) / 2, y: end.y },
      end,
    ],
    [
      start,
      { x: start.x, y: (start.y + end.y) / 2 },
      { x: end.x, y: (start.y + end.y) / 2 },
      end,
    ],
  ];
  for (const path of simple)
    if (path.slice(1).every((p, i) => segmentClear(path[i], p, obstacles)))
      return simplify(path);
  // Keep the search grid bounded; every segment still checks every obstacle.
  const nearby = [...obstacles]
    .sort(
      (a, b) =>
        distance(center(a), start) +
        distance(center(a), end) -
        distance(center(b), start) -
        distance(center(b), end),
    )
    .slice(0, 24);
  const outer = {
    left: Math.min(start.x, end.x, ...obstacles.map((r) => r.x)) - 24,
    right:
      Math.max(start.x, end.x, ...obstacles.map((r) => r.x + r.width)) + 24,
    top: Math.min(start.y, end.y, ...obstacles.map((r) => r.y)) - 24,
    bottom:
      Math.max(start.y, end.y, ...obstacles.map((r) => r.y + r.height)) + 24,
  };
  const xs = [
    ...new Set([
      start.x,
      end.x,
      outer.left,
      outer.right,
      ...nearby.flatMap((r) => [r.x - 12, r.x + r.width + 12]),
    ]),
  ].sort((a, b) => a - b);
  const ys = [
    ...new Set([
      start.y,
      end.y,
      outer.top,
      outer.bottom,
      ...nearby.flatMap((r) => [r.y - 12, r.y + r.height + 12]),
    ]),
  ].sort((a, b) => a - b);
  const coordinate = (id: number) => ({
    x: xs[Math.floor(id / ys.length)],
    y: ys[id % ys.length],
  });
  const first = xs.indexOf(start.x) * ys.length + ys.indexOf(start.y);
  const last = xs.indexOf(end.x) * ys.length + ys.indexOf(end.y);
  const open = new Queue(),
    costs = new Map<number, number>(),
    previous = new Map<number, number>();
  costs.set(first * 3, 0);
  open.push({ id: first * 3, score: distance(start, end) });
  let iterations = 0;
  while (open.items.length && iterations++ < 8000) {
    const { id } = open.pop(),
      grid = Math.floor(id / 3),
      axis = id % 3;
    const point = coordinate(grid);
    if (grid === last) {
      const path = [point];
      let current = id;
      while (previous.has(current)) {
        current = previous.get(current)!;
        path.push(coordinate(Math.floor(current / 3)));
      }
      return simplify(path.reverse());
    }
    const x = Math.floor(grid / ys.length),
      y = grid % ys.length;
    for (const [nx, ny, nextAxis] of [
      [x - 1, y, 1],
      [x + 1, y, 1],
      [x, y - 1, 2],
      [x, y + 1, 2],
    ]) {
      if (nx < 0 || ny < 0 || nx >= xs.length || ny >= ys.length) continue;
      const neighbor = { x: xs[nx], y: ys[ny] };
      if (
        obstacles.some((r) => inside(neighbor, r)) ||
        !segmentClear(point, neighbor, obstacles)
      )
        continue;
      const next = (nx * ys.length + ny) * 3 + nextAxis;
      const cost =
        costs.get(id)! +
        distance(point, neighbor) +
        (axis && axis !== nextAxis ? 22 : 0);
      if (cost >= (costs.get(next) ?? Infinity)) continue;
      costs.set(next, cost);
      previous.set(next, id);
      open.push({ id: next, score: cost + distance(neighbor, end) });
    }
  }
}

export function routeEdge(
  source: Rect,
  target: Rect,
  obstacles: Rect[],
  lane = 0,
  labelWidth = 90,
): Route | undefined {
  const preferred = facingSides(source, target);
  const pairs: [Side, Side][] = [
    preferred,
    ["right", "left"],
    ["left", "right"],
    ["bottom", "top"],
    ["top", "bottom"],
  ];
  const blocks = [
    ...obstacles.map((r) => ({
      x: r.x - 10,
      y: r.y - 10,
      width: r.width + 20,
      height: r.height + 20,
    })),
    ...(!contains(source, target) ? [source] : []),
    ...(!contains(target, source) ? [target] : []),
  ];
  for (const [sourceSide, targetSide] of pairs) {
    const a = port(source, sourceSide),
      b = port(target, targetSide);
    const start = {
      x: a.x + directions[sourceSide].x * 24,
      y: a.y + directions[sourceSide].y * 24,
    };
    const end = {
      x: b.x + directions[targetSide].x * 24,
      y: b.y + directions[targetSide].y * 24,
    };
    if (!segmentClear(a, start, blocks) || !segmentClear(end, b, blocks))
      continue;
    // Separate reciprocal paths after leaving the card, keeping all ports at midpoints.
    const laneStart = {
      x: start.x + (directions[sourceSide].y ? lane : 0),
      y: start.y + (directions[sourceSide].x ? lane : 0),
    };
    const laneEnd = {
      x: end.x + (directions[targetSide].y ? lane : 0),
      y: end.y + (directions[targetSide].x ? lane : 0),
    };
    if (
      !segmentClear(start, laneStart, blocks) ||
      !segmentClear(laneEnd, end, blocks)
    )
      continue;
    const middle = corridor(laneStart, laneEnd, blocks);
    if (!middle) continue;
    const points = simplify([a, start, ...middle, end, b]);
    // Keep the whole label off cards, including labels on vertical segments.
    const segments = points
      .slice(1)
      .map((end, i) => ({ start: points[i], end }))
      .sort((a, b) => distance(b.start, b.end) - distance(a.start, a.end));
    const fractions = [
      lane < 0 ? 0.27 : lane > 0 ? 0.73 : 0.5,
      0.5,
      0.15,
      0.85,
    ];
    const candidates = segments.flatMap(({ start, end }) =>
      fractions.map((fraction) => ({
        x: Math.min(start.x, end.x) + Math.abs(start.x - end.x) * fraction,
        y: Math.min(start.y, end.y) + Math.abs(start.y - end.y) * fraction,
      })),
    );
    const clearLabel = (p: Point) =>
      [source, target, ...obstacles].every(
        (r) =>
          p.x + labelWidth / 2 < r.x - 3 ||
          p.x - labelWidth / 2 > r.x + r.width + 3 ||
          p.y + 12 < r.y - 3 ||
          p.y - 12 > r.y + r.height + 3,
      );
    const label =
      candidates.find(clearLabel) ??
      candidates
        .flatMap((p) => [
          { x: p.x - labelWidth / 2 - 16, y: p.y },
          { x: p.x + labelWidth / 2 + 16, y: p.y },
        ])
        .find(clearLabel) ??
      candidates[0];
    return { points, sourceSide, targetSide, label };
  }
}

export function roundedPath(points: Point[], radius = 8): string {
  if (!points.length) return "";
  let path = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length - 1; i++) {
    const a = points[i - 1],
      b = points[i],
      c = points[i + 1];
    const r = Math.min(radius, distance(a, b) / 2, distance(b, c) / 2);
    const before = {
      x: b.x + Math.sign(a.x - b.x) * r,
      y: b.y + Math.sign(a.y - b.y) * r,
    };
    const after = {
      x: b.x + Math.sign(c.x - b.x) * r,
      y: b.y + Math.sign(c.y - b.y) * r,
    };
    path += ` L ${before.x} ${before.y} Q ${b.x} ${b.y} ${after.x} ${after.y}`;
  }
  return path + ` L ${points.at(-1)!.x} ${points.at(-1)!.y}`;
}
