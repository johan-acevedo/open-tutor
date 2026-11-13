import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// The Smart Screen shell (screen/shell/) lives outside the web root and plain
// `?raw` imports of it come back empty for CSS, so a tiny plugin serves the
// files as virtual text modules instead. Single source of truth, no copies.
// Works in dev, build and vitest alike.
function screenTextPlugin() {
  const shellDir = fileURLToPath(new URL('../screen/shell/', import.meta.url));
  const examplesDir = fileURLToPath(new URL('../screen/examples/', import.meta.url));
  const read = (dir: string, name: string) => readFileSync(dir + name, 'utf8');
  return {
    name: 'screen-text',
    resolveId(id: string) {
      if (id === 'virtual:screen-shell' || id === 'virtual:screen-demo') return `\0${id}`;
      return null;
    },
    load(id: string) {
      if (id === '\0virtual:screen-shell') {
        return (
          `export const frameHtml = ${JSON.stringify(read(shellDir, 'frame.html'))};\n` +
          `export const shellCss = ${JSON.stringify(read(shellDir, 'shell.css'))};\n` +
          `export const shellJs = ${JSON.stringify(read(shellDir, 'shell.js'))};\n` +
          `export const mapLanData = ${JSON.stringify(read(shellDir, 'data/lan-sverige.json'))};\n`
        );
      }
      if (id === '\0virtual:screen-demo') {
        const names: Array<[string, string]> = [
          ['klockanBody', 'klockan.html'],
          ['klockanPatch', 'klockan.patch.html'],
          ['divisionBody', 'division.html'],
          ['divisionPatch', 'division.patch.html'],
        ];
        return names
          .map(([idn, n]) => `export const ${idn} = ${JSON.stringify(read(examplesDir, n))};\n`)
          .join('');
      }
      return null;
    },
  };
}

// Vite dev server proxies /api to the FastAPI web service.
// `npm run build` outputs web/dist (served by FastAPI).
export default defineConfig({
  plugins: [react(), screenTextPlugin()],
  server: {
    proxy: {
      '/materials': 'http://127.0.0.1:8710',
      '/api': 'http://127.0.0.1:8710',
    },
  },
  build: {
    outDir: 'dist',
  },
  test: {
    environment: 'jsdom',
    globals: false,
  },
});
