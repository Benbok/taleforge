/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Сборка кладётся рядом с сервером: FastAPI раздаёт app/web/dist как одностраничный клиент.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "../app/web/dist", emptyOutDir: true },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
  test: { environment: "jsdom" },
});
