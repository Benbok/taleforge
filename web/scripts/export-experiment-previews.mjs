import { build } from "vite";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const output = resolve(import.meta.dirname, "../.experiment-previews-build");
await build({
  configFile: false,
  publicDir: false,
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
await renderAllExperimentPreviews({ templatesOnly: process.argv.includes("--templates-only") });
console.log("All experiment previews rendered successfully.");
