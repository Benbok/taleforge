/** Trace the union of occupied cells, preserving holes and disconnected groups. */
export interface FeatureFootprint {
  cells: [number, number][];
  path: string;
  x: number;
  y: number;
  width: number;
  height: number;
}
type Point = [number, number];
const key = ([x, y]: Point) => `${x},${y}`;
const neighbors: Point[] = [[1, 0], [0, 1], [-1, 0], [0, -1]];

export function featureFootprints(rects: number[][]): FeatureFootprint[] {
  const remaining = new Map<string, Point>();
  for (const [x0, y0, x1 = x0, y1 = y0] of rects) {
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) remaining.set(`${x},${y}`, [x, y]);
  }
  const groups: FeatureFootprint[] = [];
  while (remaining.size) {
    const first = remaining.values().next().value!;
    const cells: Point[] = [first];
    remaining.delete(key(first));
    for (let index = 0; index < cells.length; index++) {
      const [x, y] = cells[index];
      for (const [dx, dy] of neighbors) {
        const point = remaining.get(`${x + dx},${y + dy}`);
        if (point) { cells.push(point); remaining.delete(key(point)); }
      }
    }
    const occupied = new Set(cells.map(key));
    const edges = new Map<string, { from: Point; to: Point; direction: number }[]>();
    for (const [x, y] of cells) {
      const corners: Point[] = [[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1]];
      const outside: Point[] = [[x, y - 1], [x + 1, y], [x, y + 1], [x - 1, y]];
      for (let direction = 0; direction < 4; direction++) {
        if (occupied.has(key(outside[direction]))) continue;
        const from = corners[direction], to = corners[(direction + 1) % 4];
        const list = edges.get(key(from)) ?? [];
        list.push({ from, to, direction });
        edges.set(key(from), list);
      }
    }
    const paths: string[] = [];
    while (edges.size) {
      const start = edges.values().next().value![0].from;
      let point = start, direction = 0;
      const commands = [`M${start[0]} ${start[1]}`];
      do {
        const list = edges.get(key(point))!;
        // At a touching corner keep the occupied region on the right of the contour.
        const preference = [1, 0, 3, 2];
        list.sort((a, b) => preference.indexOf((a.direction - direction + 4) % 4)
          - preference.indexOf((b.direction - direction + 4) % 4));
        const edge = list.shift()!;
        if (!list.length) edges.delete(key(point));
        point = edge.to;
        direction = edge.direction;
        commands.push(`L${point[0]} ${point[1]}`);
      } while (key(point) !== key(start));
      paths.push(`${commands.join(" ")} Z`);
    }
    const x = Math.min(...cells.map((c) => c[0])), y = Math.min(...cells.map((c) => c[1]));
    groups.push({ cells, path: paths.join(" "), x, y,
      width: Math.max(...cells.map((c) => c[0])) - x + 1, height: Math.max(...cells.map((c) => c[1])) - y + 1 });
  }
  return groups;
}
