import { build } from "vite";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const output = resolve(import.meta.dirname, "../.map-examples-build");
await build({
  configFile: false,
  build: { ssr: resolve(import.meta.dirname, "render-location-maps.tsx"), outDir: output,
    emptyOutDir: true, rollupOptions: { output: { entryFileNames: "render.mjs" } } },
  esbuild: { jsx: "automatic" },
});
const { renderExamples } = await import(pathToFileURL(resolve(output, "render.mjs")).href);
await renderExamples();
