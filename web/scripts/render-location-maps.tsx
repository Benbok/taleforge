import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { LocationMapSvg, locationTokens } from "../src/game/LocationMap";
import { mapForDisplay } from "../src/game/map";

export async function renderExamples() {
  const directory = resolve(process.cwd(), "../docs/examples/location-maps");
  for (const name of ["temple-known", "field-stream-bridge", "hero-memory"]) {
    const m = mapForDisplay(JSON.parse(await readFile(resolve(directory, `${name}.json`), "utf8")));
    if (!m.location_map) throw new Error(`Нет плана ${name}`);
    const svg = renderToStaticMarkup(<LocationMapSvg map={m.location_map} liveSketch={m.sketch}
      tokens={locationTokens(m)} idPrefix={`example-${name}`} />)
      .replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ');
    await writeFile(resolve(directory, `${name}.svg`), svg + "\n", "utf8");
  }
}
