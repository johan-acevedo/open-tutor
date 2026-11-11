import { defineConfig } from "vite";

export default defineConfig({
  root: ".",
  publicDir: false,
  build: {
    outDir: "../public",
    emptyOutDir: true,
    target: "es2022",
    sourcemap: false,
  },
  worker: {
    format: "es",
  },
  server: {
    port: 5173,
  },
});
