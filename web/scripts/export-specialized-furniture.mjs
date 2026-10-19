import { build } from "vite";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const output = resolve(import.meta.dirname, "../.experiment-previews-build/furniture");
await build({ configFile: false, publicDir: false,
  build: { ssr: resolve(import.meta.dirname, "render-specialized-furniture.tsx"), outDir: output,
    emptyOutDir: true, rollupOptions: { output: { entryFileNames: "render.mjs" } } },
  esbuild: { jsx: "automatic" },
});
const { renderSpecializedFurniture } = await import(pathToFileURL(resolve(output, "render.mjs")).href);
await renderSpecializedFurniture(resolve(import.meta.dirname, "../../experiments/location-layout-templates/quality-v3/specialized-furniture.svg"));
