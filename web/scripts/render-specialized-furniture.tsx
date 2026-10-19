import { writeFile } from "node:fs/promises";
import { renderToStaticMarkup } from "react-dom/server";
import { MapFeature } from "../src/game/MapFeature";

export async function renderSpecializedFurniture(target: string) {
  const samples = [
    ["Письменный стол", "desk"], ["Королевский трон", "throne"], ["Оскверненный трон", "defiled_throne"],
    ["Стол для пыток", "torture_table"], ["Стол для инструментов", "tool_table"],
    ["Стол с оружием", "weapon_table"], ["Кресло для допросов", "torture_chair"],
    ["Стойка с орудиями", "weapon_rack"], ["Обеденный стол", "table"],
  ];
  const svg = renderToStaticMarkup(<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="975" viewBox="0 0 1080 975">
    <rect width="1080" height="975" fill="#171b20" />
    {samples.map(([name, form], i) => <g key={form} transform={`translate(${i % 3 * 360} ${Math.floor(i / 3) * 325})`}>
      <text x="24" y="34" fill="#e5d7bd" fontSize="18" fontFamily="sans-serif">{name}</text>
      <g transform="translate(28 70) scale(95)">
        <MapFeature feature={{ id: `sample-${form}`, name, kind: "furniture", visual_key: `feature:${form}`, cells: [[0, 0, 2, 1]] }} idPrefix={`sample-${form}`} />
      </g>
    </g>)}
  </svg>);
  await writeFile(target, svg + "\n", "utf8");
}
