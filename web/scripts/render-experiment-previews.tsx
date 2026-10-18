import { copyFile, mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { LocationMapSvg } from "../src/game/LocationMap";
import type { MapLocationPlan } from "../src/game/map";

export const STYLES = `
<defs>
  <style>
    :root, svg {
      --tf-bg: #0f1012;
      --tf-surface: #17181c;
      --tf-surface-2: #1b1c20;
      --tf-raised: #121316;
      --tf-border: #2a2b31;
      --tf-border-soft: #24252a;
      --tf-text: #ece6dc;
      --tf-text-2: #cfc8bb;
      --tf-muted: #a8a296;
      --tf-faint: #8a857c;
      --tf-accent: #c98a4b;
      --tf-accent-hi: #d59a5c;
      --tf-accent-text: #1a120a;
      --tf-patina: #5fae9f;
      --tf-patina-hi: #7fc2b4;
      --tf-ember: #c4553f;
      --tf-ember-hi: #e0876f;
      --tf-ember-bg: #16120f;
      --tf-warn: #d99a2b;
      --tf-ok: #72c491;
      --tf-bad: #ed8b85;
      --tf-map-floor: #272c30;
      --tf-map-stone: #2e3338;
      --tf-map-wood: #3a2e24;
      --tf-map-grass: #26382b;
      --tf-map-earth: #362e26;
      --tf-map-water: #1b3244;
      --tf-map-water-mark: #4a7a9e33;
      --tf-map-wall-stroke: #222428;
      --tf-map-edge: #756;
      --tf-map-road: #8c7b58;
      --tf-map-path: #b6a66a;
      --tf-map-stream: #497b98;
      --tf-map-bridge: #8a623c;
      --tf-map-mark: #ffffff18;
      --tf-map-wall: #74777e;
      --tf-map-opening: #db9d5f;
      --tf-entity-creature: #e06c5f;
      --tf-entity-npc: #6ea8e0;
      --tf-entity-item: #d9b44a;
      --tf-entity-location: #6fbf86;
      --tf-entity-lore: #9a9fa8;
      background-color: #0f1012;
    }
  </style>
</defs>
`;

function injectSvgDefs(svgString: string, desc?: string): string {
  const descTag = desc ? `<desc>${desc}</desc>\n` : "";
  return svgString
    .replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ')
    .replace(/(<svg[^>]*>)/, `$1\n${descTag}${STYLES}`);
}

interface RenderPayload {
  template_id: string;
  root_id: string;
  entry: string;
  levels: number[];
  areas: Array<{
    id: string;
    name: string;
    offset: [number, number];
    level: number;
    secret?: boolean;
    status: "here" | "remembered";
    revision: number;
    sketch: any;
  }>;
}

const COMPARISON_KEY_AREAS: Record<string, string> = {
  tavern_roadside: "common_room",
  port_quay_warehouse: "cargo_pier",
  cave_passages_grotto: "great_grotto",
};

export async function renderPayloadViews(
  payload: RenderPayload,
  targetDir: string,
  prefix: string,
  keyAreaId?: string,
  filePrefix = ""
) {
  await mkdir(targetDir, { recursive: true });

  // 1. Авторский общий план всех частей (overview_all.svg)
  const lvl = 0;
  const overviewPlan: MapLocationPlan = {
    root_id: payload.root_id,
    here_id: payload.entry,
    areas: payload.areas.map((a) => ({
      ...a,
      status: "here", // на авторском плане все части видны с полной непрозрачностью
    })),
  };
  const overviewSvg = injectSvgDefs(
    renderToStaticMarkup(
      <LocationMapSvg
        map={overviewPlan}
        activeLevel={lvl}
        idPrefix={`${prefix}-overview`}
      />
    ),
    "Авторский общий план локации (все части открыты с полной непрозрачностью)"
  );
  const overviewName = filePrefix ? `${filePrefix}_overview.svg` : "overview_all.svg";
  await writeFile(resolve(targetDir, overviewName), overviewSvg + "\n", "utf8");

  // 2. Ключевой участок крупно (key_area.svg)
  const targetKeyId = keyAreaId ?? payload.areas[0]?.id;
  const targetArea = payload.areas.find((a) => a.id === targetKeyId) ?? payload.areas[0];
  if (targetArea) {
    const keyPlan: MapLocationPlan = {
      root_id: payload.root_id,
      here_id: targetArea.id,
      areas: [
        {
          ...targetArea,
          offset: [0, 0],
          status: "here",
        },
      ],
    };
    const keySvg = injectSvgDefs(
      renderToStaticMarkup(
        <LocationMapSvg
          map={keyPlan}
          activeLevel={targetArea.level}
          idPrefix={`${prefix}-key`}
        />
      ),
      `Ключевой участок крупно: ${targetArea.name} (${targetArea.id})`
    );
    const keyName = filePrefix ? `${filePrefix}_key.svg` : "key_area.svg";
    await writeFile(resolve(targetDir, keyName), keySvg + "\n", "utf8");
  }

  // 3. Обычный вид игрока (player_view.svg)
  // Входной участок — здесь (here), непосредственно связанные несекретные соседи — запомнены (remembered),
  // тайные участки — строго скрыты по данным blueprint (area.secret).
  const entryArea = payload.areas.find((a) => a.id === payload.entry) ?? payload.areas[0];
  if (entryArea) {
    const connectedAreaIds = new Set<string>();
    for (const exit of entryArea.sketch.exits ?? []) {
      if (exit.to && exit.to !== payload.root_id && !exit.hidden) {
        const dest = payload.areas.find((a) => a.id === exit.to);
        if (dest && !dest.secret) {
          connectedAreaIds.add(exit.to);
        }
      }
    }

    const playerAreas = payload.areas
      .filter((a) => (a.id === entryArea.id || connectedAreaIds.has(a.id)) && !a.secret)
      .map((a) => ({
        ...a,
        status: (a.id === entryArea.id ? "here" : "remembered") as "here" | "remembered",
      }));

    const playerPlan: MapLocationPlan = {
      root_id: payload.root_id,
      here_id: entryArea.id,
      areas: playerAreas,
    };

    const playerSvg = injectSvgDefs(
      renderToStaticMarkup(
        <LocationMapSvg
          map={playerPlan}
          activeLevel={entryArea.level}
          idPrefix={`${prefix}-player`}
        />
      ),
      "Пример состояния игрока (player_view): отряд на входном участке, смежные открытые участки запомнены. Соседство на карте само по себе не означает, что участок уже посещён."
    );
    const playerName = filePrefix ? `${filePrefix}_player.svg` : "player_view.svg";
    await writeFile(resolve(targetDir, playerName), playerSvg + "\n", "utf8");
  }
}

export async function renderAllExperimentPreviews({ templatesOnly = false } = {}) {
  const templatesRoot = resolve(process.cwd(), "../experiments/location-layout-templates/templates");
  const comparisonsRoot = resolve(process.cwd(), "../experiments/location-layout-templates/comparisons");
  const entries = await readdir(templatesRoot, { withFileTypes: true });
  const templateDirs = entries.filter((e) => e.isDirectory()).map((e) => e.name);

  for (const tid of templateDirs) {
    const tdir = resolve(templatesRoot, tid);
    const payloadPath = resolve(tdir, "render_payload.json");
    let payloadRaw: string;
    try {
      payloadRaw = await readFile(payloadPath, "utf8");
    } catch {
      continue;
    }
    const payload = JSON.parse(payloadRaw) as RenderPayload;
    const previewsDir = resolve(tdir, "previews");
    await mkdir(previewsDir, { recursive: true });

    // 1. Рендерим общий план для каждого уровня
    for (const lvl of payload.levels) {
      const plan: MapLocationPlan = {
        root_id: payload.root_id,
        here_id: payload.entry,
        areas: payload.areas.map((a) => ({
          ...a,
          status: "here",
        })),
      };

      const rawSvg = renderToStaticMarkup(
        <LocationMapSvg
          map={plan}
          activeLevel={lvl}
          idPrefix={`preview-${tid}-lvl-${lvl}`}
        />
      );
      const styledSvg = injectSvgDefs(rawSvg);
      const filename = `overview_level_${lvl}.svg`;
      await writeFile(resolve(previewsDir, filename), styledSvg + "\n", "utf8");
    }

    // 2. Рендерим каждый участок отдельно
    for (const area of payload.areas) {
      const singleAreaPlan: MapLocationPlan = {
        root_id: payload.root_id,
        here_id: area.id,
        areas: [
          {
            ...area,
            offset: [0, 0],
            status: "here",
          },
        ],
      };

      const rawSvg = renderToStaticMarkup(
        <LocationMapSvg
          map={singleAreaPlan}
          activeLevel={area.level}
          idPrefix={`preview-${tid}-area-${area.id}`}
        />
      );
      const styledSvg = injectSvgDefs(rawSvg);
      const filename = `area_${area.id}.svg`;
      await writeFile(resolve(previewsDir, filename), styledSvg + "\n", "utf8");
    }

    await renderPayloadViews(payload, previewsDir, `catalog-${tid}`, COMPARISON_KEY_AREAS[tid]);
    console.log(`[renderer] Rendered standard SVG previews for ${tid}`);
  }

  if (templatesOnly) return;

  // 3. Рендерим честные сравнения для 3 ключевых шаблонов:
  // - Сравнение старых и новых данных одним renderer (layout_comparison)
  // - Сравнение старой и новой отрисовки на одинаковых данных (renderer_comparison)
  for (const [tid, keyAreaId] of Object.entries(COMPARISON_KEY_AREAS)) {
    const compDir = resolve(comparisonsRoot, tid);
    const beforeDir = resolve(compDir, "before");
    const afterDir = resolve(compDir, "after");
    const layoutDiffDir = resolve(compDir, "layout_comparison");
    const rendererDiffDir = resolve(compDir, "renderer_comparison");

    await mkdir(layoutDiffDir, { recursive: true });
    await mkdir(rendererDiffDir, { recursive: true });

    // A. Загружаем исходный before payload и актуальный after payload
    const beforePayloadPath = resolve(beforeDir, "render_payload.json");
    const afterPayloadPath = resolve(templatesRoot, tid, "render_payload.json");

    let beforePayload: RenderPayload | null = null;
    let afterPayload: RenderPayload | null = null;

    try {
      beforePayload = JSON.parse(await readFile(beforePayloadPath, "utf8")) as RenderPayload;
    } catch (e) {
      console.warn(`[comparisons] No before payload for ${tid}:`, e);
    }

    try {
      afterPayload = JSON.parse(await readFile(afterPayloadPath, "utf8")) as RenderPayload;
    } catch (e) {
      console.warn(`[comparisons] No after payload for ${tid}:`, e);
    }

    if (beforePayload && afterPayload) {
      // 1. Сравнение старых и новых данных одним новым renderer (layout_comparison)
      await renderPayloadViews(
        beforePayload,
        layoutDiffDir,
        `layout-comp-before-${tid}`,
        keyAreaId,
        "before_layout"
      );
      await renderPayloadViews(
        afterPayload,
        layoutDiffDir,
        `layout-comp-after-${tid}`,
        keyAreaId,
        "after_layout"
      );

      // Также обновляем before/ и after/
      await renderPayloadViews(beforePayload, beforeDir, `comp-before-${tid}`, keyAreaId);
      await renderPayloadViews(afterPayload, afterDir, `comp-after-${tid}`, keyAreaId);

      // 2. Сравнение старой и новой отрисовки на одинаковых данных (renderer_comparison)
      // Берем оригинальные SVG старого renderer, сохраненные в before/:
      const origOldOverviewPath = resolve(beforeDir, "overview_level_0.svg");
      const origOldKeyPath = resolve(beforeDir, `area_${keyAreaId}.svg`);

      try {
        await copyFile(origOldOverviewPath, resolve(rendererDiffDir, "old_renderer_overview.svg"));
        await copyFile(origOldKeyPath, resolve(rendererDiffDir, "old_renderer_key_area.svg"));
      } catch (e) {
        console.warn(`[comparisons] Could not copy original old SVG for ${tid}:`, e);
      }

      // Тот же исходный before payload, отрисованный новым renderer:
      const newRendererOverviewPlan: MapLocationPlan = {
        root_id: beforePayload.root_id,
        here_id: beforePayload.entry,
        areas: beforePayload.areas.map((a) => ({ ...a, status: "here" })),
      };
      const newRendererOverviewSvg = injectSvgDefs(
        renderToStaticMarkup(
          <LocationMapSvg
            map={newRendererOverviewPlan}
            activeLevel={0}
            idPrefix={`renderer-comp-new-${tid}-overview`}
          />
        ),
        "Новая отрисовка на исходных (старых) данных локации"
      );
      await writeFile(
        resolve(rendererDiffDir, "new_renderer_overview.svg"),
        newRendererOverviewSvg + "\n",
        "utf8"
      );

      const targetArea = beforePayload.areas.find((a) => a.id === keyAreaId) ?? beforePayload.areas[0];
      if (targetArea) {
        const newRendererKeyPlan: MapLocationPlan = {
          root_id: beforePayload.root_id,
          here_id: targetArea.id,
          areas: [{ ...targetArea, offset: [0, 0], status: "here" }],
        };
        const newRendererKeySvg = injectSvgDefs(
          renderToStaticMarkup(
            <LocationMapSvg
              map={newRendererKeyPlan}
              activeLevel={targetArea.level}
              idPrefix={`renderer-comp-new-${tid}-key`}
            />
          ),
          `Новая отрисовка ключевого участка на исходных данных: ${targetArea.name}`
        );
        await writeFile(
          resolve(rendererDiffDir, "new_renderer_key_area.svg"),
          newRendererKeySvg + "\n",
          "utf8"
        );
      }

      console.log(`[comparisons] Rendered layout and renderer comparisons for ${tid}`);
    }
  }
}
