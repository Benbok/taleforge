import { access, mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../../experiments/location-layout-templates");
const output = resolve(root, "quality-v2");
const manifest = JSON.parse(await readFile(resolve(root, "manifest.json"), "utf8"));
const escape = (value) => String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const comparisons = [
  ["tavern_roadside", "Придорожная таверна", "Отдельные группы столов, Г-образная стойка и спальные места. Между входом, залом и служебными помещениями остаются свободные проходы."],
  ["cave_passages_grotto", "Пещера с подземным озером", "Просторный грот со скальными островками и путями обхода. Природный камень, мох и звериная лежка получили собственный рисунок."],
  ["port_quay_warehouse", "Гавань и портовый склад", "Узкий деревянный причал с водой по обе стороны, грузовой кран и склад с проходами между стеллажами и штабелями."],
];
for (const [id] of comparisons) {
  for (const name of ["overview_all.svg", "key_area.svg", "player_view.svg"]) {
    await access(resolve(output, "before", id, "previews", name));
    await access(resolve(root, "templates", id, "previews", name));
  }
}
const paired = comparisons.map(([id, title, description], index) => `
<section class="comparison" aria-labelledby="title-${id}">
  <div class="section-heading"><span class="number">0${index + 1}</span><div><h2 id="title-${id}">${escape(title)}</h2><p>${escape(description)}</p></div></div>
  <div class="pair">
    ${[["before", "Было", `before/${id}/previews`], ["after", "Стало", `../templates/${id}/previews`]].map(([state, label, base]) => `
    <figure class="${state}"><figcaption><span>${label}</span>${state === "after" ? '<span class="badge">Обновлено</span>' : '<span class="muted">Исходный вариант</span>'}</figcaption>
      <a class="map-link" href="${base}/overview_all.svg" target="_blank" rel="noopener" data-base="${base}" aria-label="${escape(title)} — ${label}">
        <img src="${base}/overview_all.svg" alt="${escape(title)} — ${label}" width="800" height="520" />
      </a>
    </figure>`).join("")}
  </div>
</section>`).join("");

const cards = [];
for (const template of manifest.templates) {
  const id = template.id;
  const validation = JSON.parse(await readFile(resolve(root, "templates", id, "validation.json"), "utf8"));
  const base = `../templates/${encodeURIComponent(id)}/previews`;
  await access(resolve(root, "templates", id, "previews/overview_all.svg"));
  cards.push(`<article class="card">
    <a href="${base}/overview_all.svg" target="_blank" rel="noopener"><img src="${base}/overview_all.svg" alt="${escape(template.variant_name)}" width="600" height="400" loading="lazy" /></a>
    <div class="card-copy"><div class="eyebrow">${escape(({ tavern: "Таверна", temple: "Храм", cave: "Пещера", forest: "Лес", port: "Порт", ruins: "Руины" })[template.archetype])}</div>
    <h3>${escape(template.variant_name)}</h3><p>${escape(template.purpose)}</p>
    <div class="levels">${validation.levels.map((level) => `<a href="${base}/overview_level_${level}.svg" target="_blank" rel="noopener">${level === 0 ? "Основной уровень" : `Уровень ${level}`}</a>`).join("")}</div></div>
  </article>`);
}

await mkdir(output, { recursive: true });
await writeFile(resolve(output, "index.html"), `<!doctype html>
<html lang="ru"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<title>TaleForge — локации и карты</title>
<style>
*{box-sizing:border-box}html{color-scheme:dark;scroll-behavior:smooth}body{margin:0;background:#101514;color:#e5e3d8;font:15px/1.65 system-ui,sans-serif}a{color:inherit}button{font:inherit}main{max-width:1440px;margin:auto;padding:64px 40px 80px}header{padding-bottom:38px;border-bottom:1px solid #303b35;margin-bottom:32px}.eyebrow{color:#b8a27c;font-size:11px;letter-spacing:.16em;text-transform:uppercase}h1,h2,h3{font-family:Georgia,'Times New Roman',serif;font-weight:400;line-height:1.2}h1{font-size:clamp(38px,5vw,66px);margin:18px 0 16px;letter-spacing:-.03em}header p{max-width:720px;color:#9fa89e;font-size:17px}nav{display:flex;gap:24px;margin-top:26px;font-size:13px}nav a{text-decoration:none;border-bottom:1px solid #77694b;padding-bottom:4px}.toolbar{display:flex;align-items:center;flex-wrap:wrap;gap:9px;margin:24px 0 34px}.toolbar span{margin-right:12px;font-size:12px;color:#9fa89e}button{border:1px solid #354039;color:#aeb7ab;background:transparent;padding:8px 16px;cursor:pointer;border-radius:4px}button[aria-pressed=true]{background:#c2ae86;border-color:#c2ae86;color:#161c18}button:focus-visible,a:focus-visible{outline:2px solid #dfcfaa;outline-offset:4px}.comparison{margin:0 0 48px}.section-heading{display:flex;gap:20px;margin-bottom:18px;align-items:flex-start}.number{color:#7d8b7c;font:18px/1.2 Georgia,serif;padding-top:4px}h2{font-size:28px;margin:0 0 10px}.section-heading p{margin:0;color:#9fa89e;max-width:850px;font-size:14px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}figure{margin:0;border:1px solid #2e3831;background:#111;color:#b1b7ac;border-radius:7px;overflow:hidden}.after{border-color:#6d7051}figcaption{display:flex;align-items:center;justify-content:space-between;padding:12px 17px;border-bottom:1px solid #27302b;font-size:13px;letter-spacing:.025em}.after figcaption{background:#1b231d;color:#ded8ba}.badge{font-size:10px;text-transform:uppercase;letter-spacing:.13em;color:#b8be92}.muted{font-size:11px;color:#6f7972}.map-link{display:flex;min-height:360px;align-items:center}.map-link img{display:block;width:100%;height:360px;object-fit:contain}.collection-heading{padding:36px 0 24px;border-top:1px solid #303b35}.collection-heading p{color:#9fa89e;margin:0}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.card{border:1px solid #2e3831;background:#151c18;border-radius:6px;overflow:hidden}.card img{width:100%;height:230px;display:block;object-fit:contain;background:#101112}.card-copy{padding:18px 20px 20px}h3{font-size:22px;margin:9px 0 12px}.card p{font-size:12px;color:#9fa89e;margin:0 0 16px}.levels{display:flex;gap:13px;flex-wrap:wrap;font-size:11px}.levels a{color:#c2b18b;text-decoration:none;border-bottom:1px solid #514f3c}footer{padding-top:44px;color:#748171;font-size:12px}@media(max-width:850px){main{padding:36px 20px}.cards{grid-template-columns:repeat(2,1fr)}.map-link,.map-link img{min-height:260px;height:260px}.pair{gap:10px}}@media(max-width:560px){.pair,.cards{grid-template-columns:1fr}h1{font-size:40px}.toolbar span{width:100%}.map-link,.map-link img{height:300px}.number{display:none}}@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
</style></head><body><main>
<header><div class="eyebrow">TaleForge · Атлас локаций</div><h1>Места, в которых<br />есть что исследовать</h1><p>Логичные пространства, узнаваемая обстановка и материалы. Три подробных сравнения и вся коллекция из двенадцати тактических карт.</p><nav><a href="#comparisons">До и после</a><a href="#collection">Все 12 локаций</a></nav></header>
<div id="comparisons" class="toolbar" role="group" aria-label="Представление сравнений"><span>Представление</span><button type="button" data-view="overview_all.svg" aria-pressed="true">Общий план</button><button type="button" data-view="key_area.svg" aria-pressed="false">Ключевой участок</button><button type="button" data-view="player_view.svg" aria-pressed="false">Вид игрока</button></div>
${paired}
<section id="collection"><div class="collection-heading"><div class="eyebrow">Шесть типов мест · по два варианта</div><h2>Вся коллекция</h2><p>Откройте карту, чтобы рассмотреть детали. Для многоуровневых мест доступны отдельные планы этажей.</p></div><div class="cards">${cards.join("")}</div></section>
<footer>Общие планы предназначены для автора. «Вид игрока» — пример с ограниченным набором известных участков.</footer>
</main><script>
document.querySelectorAll('button[data-view]').forEach(function(button){button.addEventListener('click',function(){document.querySelectorAll('button[data-view]').forEach(function(other){other.setAttribute('aria-pressed',String(other===button))});document.querySelectorAll('a[data-base]').forEach(function(link){var url=link.dataset.base+'/'+button.dataset.view;link.href=url;link.querySelector('img').src=url})})});
</script></body></html>\n`, "utf8");
console.log(`Quality gallery: ${resolve(output, "index.html")}`);
