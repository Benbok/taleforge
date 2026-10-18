import { build } from "vite";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const output = resolve(import.meta.dirname, "../.experiment-previews-build");
await build({
  configFile: false,
  publicDir: false,
  build: {
    ssr: resolve(import.meta.dirname, "render-map-quality-v3.tsx"),
    outDir: output,
    emptyOutDir: true,
    rollupOptions: { output: { entryFileNames: "quality-v3.mjs" } },
  },
  esbuild: { jsx: "automatic" },
});
const { renderQualityGallery } = await import(pathToFileURL(resolve(output, "quality-v3.mjs")).href);
await renderQualityGallery();
