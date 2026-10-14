import { build } from "vite";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const output = resolve(import.meta.dirname, "../.experiment-previews-build");
await build({
  configFile: false,
  build: {
    ssr: resolve(import.meta.dirname, "render-experiment-previews.tsx"),
    outDir: output,
    emptyOutDir: true,
    rollupOptions: { output: { entryFileNames: "render.mjs" } },
  },
  esbuild: { jsx: "automatic" },
});
const { renderAllExperimentPreviews } = await import(
  pathToFileURL(resolve(output, "render.mjs")).href
);
await renderAllExperimentPreviews();
console.log("All experiment previews rendered successfully.");
