import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { SketchSurface } from "../src/game/SketchSurface";
import { FEATURE_VARIANTS } from "../src/game/mapPresets";
import type { Sketch } from "../src/game/map";
import { STYLES, renderPayloadViews } from "./render-experiment-previews";

const root = resolve(import.meta.dirname, "../../experiments/location-layout-templates");
// The bundle runs from web/.experiment-previews-build, the same relative depth as scripts/.
const output = resolve(root, "quality-v3");
const escape = (value: string) => value.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

function footprint(key: string): number[][] {
  if (["feature:table", "feature:altar"].includes(key)) return [[1, 1, 2, 2]];
  if (key === "feature:counter") return [[1, 1, 3, 1], [3, 2, 3, 2]];
  if (key === "feature:bed") return [[2, 1, 2, 2]];
  if (["feature:bench", "feature:shelf", "feature:net"].includes(key)) return [[1, 2, 3, 2]];
  if (["feature:crate", "feature:barrel", "feature:rock", "feature:tree", "feature:shrub", "feature:rubble"].includes(key)) return [[1, 1, 2, 2]];
  return [[2, 1, 2, 1]];
}

export async function renderQualityGallery() {
  await mkdir(output, { recursive: true });
  const forms = Object.entries(FEATURE_VARIANTS);
  const natural = new Set(["tree", "shrub", "reeds", "lichen", "nest"]);
  const catalogue = renderToStaticMarkup(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1250 1200" width="1250" height="1200">
    <rect width="1250" height="1200" fill="#101514" />
    {forms.map(([key, visual], index) => {
      const x = (index % 5) * 250, y = Math.floor(index / 5) * 240;
      const sk: Sketch = { shape: "open", cols: 5, rows: 4, walls: [], exits: [], party: [0, 0],
        material: natural.has(visual.form) ? "grass" : "stone",
        features: [{ id: `art-${visual.form}`, name: visual.label, kind: "object", visual_key: key, cells: footprint(key) }] };
      return <g key={key} transform={`translate(${x} ${y})`}>
        <rect x="7" y="7" width="236" height="224" rx="8" fill="#19211d" stroke="#354339" />
        <svg x="17" y="13" width="216" height="173" viewBox="-.1 -.1 5.2 4.2">
          <SketchSurface sketch={sk} idPrefix={`catalogue-${index}`} />
        </svg>
        <text x="125" y="210" fill="#d7d5be" textAnchor="middle" fontFamily="system-ui,sans-serif" fontSize="15">{visual.label}</text>
      </g>;
    })}
  </svg>);
  await writeFile(resolve(output, "objects.svg"), catalogue.replace(/(<svg[^>]*>)/, `$1${STYLES}`) + "\n", "utf8");
  const manifest = JSON.parse(await readFile(resolve(root, "manifest.json"), "utf8"));
  const comparisons = [
    ["tavern_roadside", "Таверна", "Зал 14×12. Группы столов со скамьями, посуда, доски и крепления, тёплый очаг."],
    ["cave_passages_grotto", "Подземный грот", "Грот 17×14. Грани камня, осыпи, лишайник и обходы скальных островков."],
    ["port_quay_warehouse", "Порт", "Причал 4×12, склад 12×10. Крепления крана, сети, обручи и грузовые ящики."],
  ];
  const pairs = comparisons.map(([id, title, description]) => `<section><h2>${title}</h2><p>${description}</p><div class="pair">
    <figure><figcaption>Предыдущая версия</figcaption><a href="before/${id}/key_area.svg"><img src="before/${id}/key_area.svg" alt="${title}: раньше" /></a></figure>
    <figure><figcaption>Новая версия</figcaption><a href="../templates/${id}/previews/key_area.svg"><img src="../templates/${id}/previews/key_area.svg" alt="${title}: сейчас" /></a></figure>
    </div></section>`).join("\n");
  const cards = manifest.templates.map((entry: { id: string; variant_name: string }) => `<a class="card" href="../templates/${entry.id}/previews/overview_all.svg"><img src="../templates/${entry.id}/previews/overview_all.svg" alt="${escape(entry.variant_name)}" /><span>${escape(entry.variant_name)}</span></a>`).join("\n");
  const generated = JSON.parse(await readFile(resolve(output, "generated/manifest.json"), "utf8"));
  const automaticCards = [];
  for (const entry of generated) {
    const directory = resolve(output, "generated", entry.id);
    const payload = JSON.parse(await readFile(resolve(directory, "render_payload.json"), "utf8"));
    await renderPayloadViews(payload, directory, entry.id);
    automaticCards.push(`<a class="card" href="generated/${entry.id}/overview_all.svg"><img src="generated/${entry.id}/overview_all.svg" alt="${escape(entry.title)}" /><span>${escape(entry.title)} · ${entry.areas} участка · ${entry.details} деталей</span></a>`);
  }
  const html = `<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TaleForge — пространство и предметы</title><style>
*{box-sizing:border-box}html{color-scheme:dark}body{margin:0;background:#101514;color:#e4e1d1;font:15px/1.6 system-ui,sans-serif}main{max-width:1380px;margin:auto;padding:42px 30px}h1,h2{font-family:Georgia,serif;font-weight:400}h1{font-size:46px;margin:0}h2{font-size:29px;margin:36px 0 8px}p{color:#a2ad9e;max-width:850px;margin:8px 0 20px}nav{display:flex;gap:24px;margin:24px 0}a{color:#d4be8e}figure{margin:0;border:1px solid #394439;border-radius:6px;overflow:hidden;background:#111}figcaption{padding:9px 16px;background:#1e2920;color:#c9c4a8}.pair{display:grid;grid-template-columns:1fr 1fr;gap:18px}.pair img{display:block;width:100%;height:360px;object-fit:contain}.catalogue{display:block;width:100%;border:1px solid #394439;border-radius:6px}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.card{display:block;background:#17201a;border:1px solid #394439;border-radius:6px;overflow:hidden;text-decoration:none}.card img{display:block;width:100%;height:250px;object-fit:contain;background:#111}.card span{display:block;padding:12px 16px}button{font:inherit;padding:8px 14px;background:#27392c;color:#e6ddc6;border:1px solid #56674d;border-radius:4px;cursor:pointer}body.before .pair figure:last-child{order:-1}footer{margin-top:30px;color:#899681;font-size:12px}@media(max-width:700px){main{padding:25px 14px}.pair{grid-template-columns:1fr}.cards{grid-template-columns:1fr 1fr}.pair img{height:280px}h1{font-size:34px}}
</style><main><h1>Пространство и предметы</h1><p>Более просторные места, подробная обстановка и узнаваемые материалы. Откройте изображение, чтобы рассмотреть детали.</p><nav><a href="#objects">25 видов предметов</a><a href="#comparison">До и после</a><a href="#maps">Все карты</a></nav>
<section id="objects"><h2>Обстановка крупным планом</h2><p>Конструкция, фактура и устойчивые вариации каждого предмета. Рисунок сохраняется при обновлении карты.</p><a href="objects.svg"><img class="catalogue" src="objects.svg" alt="Каталог 25 рисунков предметов" width="1250" height="1200"></a></section>
<section id="comparison"><h2>Сравнение с предыдущим этапом</h2><button onclick="document.body.classList.toggle('before')">Поменять стороны</button>${pairs}</section>
<section id="automatic"><h2>Автоматическая генерация</h2><p>Пять сохранённых ответов технической модели, три запасных плана и три локальных примера освещения. Все планы проходят серверную проверку геометрии.</p><div class="cards">${automaticCards.join("\n")}</div></section>
<section id="maps"><h2>Коллекция из 12 локаций</h2><div class="cards">${cards}</div></section><footer>Общие планы предназначены для автора. Сравнения сохраняют настоящие снимки предыдущей версии.</footer></main></html>\n`;
  await writeFile(resolve(output, "index.html"), html, "utf8");
  console.log(`Quality gallery: ${resolve(output, "index.html")}`);
}
