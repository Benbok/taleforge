import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const dir = resolve(root, "docs/examples/location-maps");
const esc = (s) => String(s).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;");
const cell = (x, y, color) => `<rect x="${x * 10}" y="${y * 10}" width="10" height="10" fill="${color}"/>`;
for (const file of ["field-stream-bridge", "temple-known", "hero-memory"]) {
  const map = JSON.parse(await readFile(resolve(dir, `${file}.json`), "utf8"));
  const shapes = map.areas.flatMap((area) => {
    const ox = area.offset[0] * 10;
    const oy = area.offset[1] * 10;
    const cells = area.sketch.terrain?.flatMap((t) => t.cells.map(([x, y]) => cell(x, y, t.kind === "stream" ? "#77a9c6" : t.kind === "bridge" ? "#b88a54" : "#b6a66a"))).join("") ?? "";
    return `<g transform="translate(${ox} ${oy})" data-area-id="${esc(area.id)}"><rect width="120" height="80" fill="${area.status === "remembered" ? "#e6e0d5" : "#f7f1df"}" stroke="#4b463d"/>${cells}<text x="4" y="14" font-size="5">${esc(area.name)}</text></g>`;
  }).join("");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 120" data-location-map="${esc(map.root_id)}">${shapes}</svg>\n`;
  await writeFile(resolve(dir, `${file}.svg`), svg, "utf8");
}
